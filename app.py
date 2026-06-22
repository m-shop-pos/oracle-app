import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import sqlite3
import pandas as pd
import re
from datetime import datetime
import json

# 1. เชื่อมต่อฐานข้อมูล Firebase Firestore
if not firebase_admin._apps:
    has_secrets = False
    try:
        if "firebase" in st.secrets:
            has_secrets = True
    except Exception:
        pass
        
    if has_secrets:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
    else:
        cred = credentials.Certificate('firebase-key.json')
    firebase_admin.initialize_app(cred)
db = firestore.client()

# 1. ตั้งค่าหน้าจอ (Mobile View & Thai)
st.set_page_config(page_title="Oracle", page_icon="🔮", layout="centered")

# Custom CSS for better mobile UI
st.markdown("""
<style>
    .main { padding: 1rem; }
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
    .stTextInput>div>div>input { border-radius: 8px; }
    .stTextArea>div>div>textarea { border-radius: 8px; }
    div[data-baseweb="tab-list"] { justify-content: center; }
</style>
""", unsafe_allow_html=True)

# 2. การจัดการฐานข้อมูล (SQLite)
def init_db():
    conn = sqlite3.connect('oracle.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS results (
            web_name TEXT,
            date DATE,
            round_number INTEGER,
            top_3 TEXT,
            bottom_2 TEXT,
            PRIMARY KEY (web_name, date, round_number)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS algo_stats (
            algorithm TEXT PRIMARY KEY,
            wins INTEGER,
            losses INTEGER,
            score REAL
        )
    """)
    algos = ["สูตรเลขไหล (Hot Pick)", "สูตรล็อกตามกระแส (Markov)", "สูตรเลขตาม (Cold Chasing)"]
    for algo in algos:
        c.execute('INSERT OR IGNORE INTO algo_stats (algorithm, wins, losses, score) VALUES (?, 0, 0, 0.0)', (algo,))
    conn.commit()
    conn.close()

try:
    init_db()
except:
    pass

# ฟังก์ชันบันทึกผลลัพธ์
def save_result(web_name, date, round_number, top_3, bottom_2):
    try:
        conn = sqlite3.connect('oracle.db')
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO results (web_name, date, round_number, top_3, bottom_2) 
            VALUES (?, ?, ?, ?, ?)
        """, (web_name, date, round_number, top_3, bottom_2))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการบันทึกข้อมูล: {e}")
        return False

# ฟังก์ชันเช็กข้อมูลซ้ำกับวันอื่น (เช็กทีละล็อต)
def check_batch_duplicate(web_name, target_date, matches):
    if len(matches) < 3:
        return None
    try:
        conn = sqlite3.connect('oracle.db')
        c = conn.cursor()
        c.execute("SELECT DISTINCT date FROM results WHERE web_name = ? AND date != ?", (web_name, target_date))
        other_dates = [row[0] for row in c.fetchall()]
        
        duplicate_date = None
        for d in other_dates:
            match_count = 0
            for m in matches:
                c.execute("SELECT 1 FROM results WHERE web_name = ? AND date = ? AND round_number = ? AND top_3 = ? AND bottom_2 = ?", 
                          (web_name, d, int(m['round_num']), str(m['top_3']).zfill(3), str(m['bot_2']).zfill(2)))
                if c.fetchone():
                    match_count += 1
            if match_count == len(matches):
                duplicate_date = d
                break
                
        conn.close()
        return duplicate_date
    except Exception as e:
        return None
# 3. แถบข้าง (Sidebar)
st.sidebar.title("🔮 Oracle Settings")
st.sidebar.markdown("---")
web_name = st.sidebar.text_input("🌐 ชื่อเว็บ หรือ ชื่อค่ายหวย", value="ห้องทั่วไป", help="ใช้เพื่อแยกฐานข้อมูลตามเว็บ/ห้อง")

st.markdown("##### 📈 Market Dashboard : Oracle V.1.0")
st.caption(f"Asset Data: **{web_name}**")

st.markdown("---")
st.markdown("🎯 **ตั้งค่ารูปแบบการเล่นปัจจุบัน (เพื่อรับแจ้งเตือนเมื่อถูกรางวัล)**")
col_c1, col_c2, col_c3, col_c4 = st.columns(4)
with col_c1:
    play_run = st.checkbox("🏃 วิ่ง/รูด", value=True)
with col_c2:
    play_win5 = st.checkbox("🎯 วิน 5 ตัวล่าง-บน", value=True)
with col_c3:
    play_win3 = st.checkbox("🎯 วิน 3 ตัวบน", value=True)
with col_c4:
    play_2bot = st.checkbox("🎯 2 ตัวล่าง (เจาะ)", value=False)
st.markdown("---")

# 4. แบ่งหน้าจอเป็น 3 แท็บ (ใช้ st.radio + query_params เพื่อจำหน้าเมื่อกด F5)
if "tab" in st.query_params:
    default_tab = st.query_params["tab"]
else:
    default_tab = "✍️ Data Input"

if 'active_tab' not in st.session_state:
    st.session_state.active_tab = default_tab

def on_tab_change():
    st.query_params["tab"] = st.session_state.active_tab

selected_tab = st.radio(
    "เลือกหน้าต่างการทำงาน:",
    ["✍️ Data Input", "📊 Market Data", "🔮 Trend Forecast"],
    horizontal=True,
    key="active_tab",
    label_visibility="collapsed",
    on_change=on_tab_change
)

# บังคับอัปเดต URL เผื่อเปิดครั้งแรก
st.query_params["tab"] = st.session_state.active_tab

# --- แท็บ 1: บันทึกมือ (Regex) ---
if st.session_state.active_tab == "✍️ Data Input":
    st.markdown("#### Data Entry (Manual)")
    st.caption("Import text data to the analytics database")
    
    input_date_1 = st.date_input("📅 เลือกวันที่ของข้อมูล (บันทึกมือ)", datetime.now(), key="date_manual")
    
    raw_text = st.text_area("วางข้อความดิบที่นี่", height=150, placeholder="เช่น: สรุปผล รอบที่ 12 เลข 3 ตัวบน 456 เลข 2 ตัวล่าง 78")
    
    if st.button("💾 บันทึกข้อมูล (Regex)"):
        if raw_text.strip():
            # ใช้ Regex ค้นหาทุกรอบที่มีในข้อความ
            # เพิ่ม (?s) และ Negative Lookahead (?!รอบ) เพื่อป้องกันไม่ให้ดึงเลขรอบอนาคตมาเป็นเลขผลรางวัล
            pattern = r'(?s)รอบ(?:ที่|\s)*(\d+)(?:(?!รอบ).)*?(?<!\d)(\d{3})(?!\d)(?:(?!รอบ).)*?(?<!\d)(\d{2})(?!\d)'
            matches = re.findall(pattern, raw_text)
            
            if matches:
                record_date = input_date_1.strftime("%Y-%m-%d")
                saved_count = 0
                saved_data = []
                for match in matches:
                    round_num = int(match[0])
                    top_3 = match[1]
                    bot_2 = match[2]
                    
                    if save_result(web_name, record_date, round_num, top_3, bot_2):
                        saved_count += 1
                        saved_data.append({"รอบ": round_num, "3ตัวบน": top_3, "2ตัวล่าง": bot_2})
                
                if saved_count > 0:
                    st.success(f"✅ บันทึกข้อมูลของวันที่ {record_date} สำเร็จ! จำนวน {saved_count} รอบ")
                    
                    # บันทึกรอบล่าสุดไว้เช็กการถูกรางวัลตอนท้ายสคริปต์
                    latest_r = saved_data[-1]
                    st.session_state.check_win_round = latest_r["รอบ"]
                    st.session_state.check_win_top3 = latest_r["3ตัวบน"]
                    st.session_state.check_win_bot2 = latest_r["2ตัวล่าง"]
                    
                    # เช็กข้อมูลซ้ำซ้อนกับวันอื่น
                    matches_to_check = [{'round_num': m[0], 'top_3': m[1], 'bot_2': m[2]} for m in matches]
                    dup_date = check_batch_duplicate(web_name, record_date, matches_to_check)
                    if dup_date:
                        st.error(f"🚨 **คำเตือนความผิดพลาด:** ข้อมูลที่คุณเพิ่งบันทึกไป มีหน้าตาตรงกับผลรางวัลของวันที่ **{dup_date}** แบบ 100% (เป็นไปได้สูงว่าคุณจะเลือกวันที่ในปฏิทินผิด) \n\n👉 หากบันทึกผิดวัน คุณสามารถไปกดปุ่ม 'ลบทิ้ง' ได้ที่แท็บ 'สถิติ'")
                        
                    # นำข้อมูลมาเรียงตามรอบ (น้อยไปมาก) แล้วนำมาแสดงผลเป็นตารางให้ดู
                    saved_data.sort(key=lambda x: x["รอบ"])
                    st.write("**ตารางสรุปผลที่คุณเพิ่งบันทึกเข้าไป:**")
                    st.dataframe(pd.DataFrame(saved_data), use_container_width=True, hide_index=True)
                else:
                    st.error("❌ พบข้อมูลแต่ไม่สามารถบันทึกลงฐานข้อมูลได้")
            else:
                st.warning("⚠️ ไม่สามารถสกัดข้อมูลได้ กรุณาตรวจสอบรูปแบบข้อความให้ชัดเจน (ตัวอย่าง: รอบที่ 123 สามตัวบน 456 สองตัวล่าง 78)")
        else:
            st.warning("⚠️ กรุณาวางข้อความก่อนกดบันทึก")

# Connection หลักสำหรับ แท็บ 2 และ 3

# --- แท็บ 2: ประวัติ & สถิติรวม ---
if st.session_state.active_tab == "📊 Market Data":
    st.markdown("#### Historical Market Data")
    
    # ดึงวันที่ทั้งหมดที่มีในระบบสำหรับเว็บนี้มาทำ Dropdown
    conn = sqlite3.connect('oracle.db')
    dates_df = pd.read_sql_query('SELECT DISTINCT TRIM(date) as date FROM results WHERE web_name = ? ORDER BY date DESC', conn, params=(web_name,))
    conn.close()
    
    if dates_df.empty:
        st.info(f"ยังไม่มีข้อมูลประวัติสำหรับห้อง '{web_name}'")
    else:
        available_dates = dates_df['date'].tolist()
        
        # ดึงเดือนทั้งหมดแบบไม่ซ้ำ
        available_months = sorted(list(set([d[:7] for d in available_dates if len(d) >= 7])), reverse=True)
        
        dropdown_options = ["ดูทั้งหมด"]
        for m in available_months:
            dropdown_options.append(f"ดูเฉพาะเดือน: {m}")
        dropdown_options.extend(available_dates)
        
        col_date, col_del = st.columns([1, 1])
        with col_date:
            selected_view_date = st.selectbox("📅 เลือกวันที่ หรือ เดือนที่ต้องการดู:", dropdown_options)
        with col_del:
            st.write("") # เว้นบรรทัดให้ตรงกับ Selectbox
            st.write("")
            if selected_view_date != "ดูทั้งหมด" and not selected_view_date.startswith("ดูเฉพาะเดือน:"):
                if st.button(f"🗑️ ล้างข้อมูลของวันที่ {selected_view_date}", help="ใช้สำหรับลบข้อมูลของวันนี้ทิ้งทั้งหมด (กรณีบันทึกผิด)"):
                    try:
                        conn = sqlite3.connect('oracle.db')
                        c = conn.cursor()
                        c.execute("DELETE FROM results WHERE web_name = ? AND date = ?", (web_name, selected_view_date))
                        conn.commit()
                        conn.close()
                        st.success(f"✅ ล้างข้อมูลของวันที่ {selected_view_date} เรียบร้อยแล้ว")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting data: {e}")
                        
        conn = sqlite3.connect('oracle.db')
        if selected_view_date == "ดูทั้งหมด":
            df = pd.read_sql_query('SELECT date, round_number, top_3, bottom_2 FROM results WHERE web_name = ? ORDER BY date DESC, round_number DESC', conn, params=(web_name,))
        elif selected_view_date.startswith("ดูเฉพาะเดือน:"):
            month = selected_view_date.replace("ดูเฉพาะเดือน: ", "")
            df = pd.read_sql_query('SELECT date, round_number, top_3, bottom_2 FROM results WHERE web_name = ? AND date LIKE ? ORDER BY date DESC, round_number DESC', conn, params=(web_name, f"{month}-%"))
        else:
            # ถ้าเลือกเป็นวันเดียว ให้เรียงจากรอบน้อยไปมาก (ASC) จะได้ดูง่ายขึ้น
            df = pd.read_sql_query('SELECT date, round_number, top_3, bottom_2 FROM results WHERE web_name = ? AND date = ? ORDER BY round_number ASC', conn, params=(web_name, selected_view_date))
        conn.close()
            
        # เปลี่ยนชื่อคอลัมน์ให้แสดงผลสวยงาม
        display_df = df.rename(columns={'date': 'วันที่', 'round_number': 'รอบ', 'top_3': '3ตัวบน', 'bottom_2': '2ตัวล่าง'})
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        # ---- Fake Stock Graph (Market Volatility Index) ----
        st.markdown("---")
        st.markdown("#### 📈 Market Volatility Index (MVI)")
        st.caption("Real-time asset correlation based on aggregated market data.")
        
        if not df.empty and len(df) > 1:
            try:
                # Limit to 100 latest rounds to prevent browser freeze from too many data points
                chart_data = df.head(100)[['round_number', 'top_3']].copy()
                # Convert to numeric to act as "stock price"
                chart_data['top_3'] = pd.to_numeric(chart_data['top_3'], errors='coerce').fillna(500)
                # Sort ascending by round number so graph reads left to right
                chart_data = chart_data.sort_values(by='round_number', ascending=True).set_index('round_number')
                
                # Plot the sequence
                st.line_chart(chart_data[['top_3']], color="#e74c3c", height=250)
            except Exception as e:
                pass

def get_predictions(history_df):
    if history_df.empty:
        return [], [], [], []
    
    # --- 1. Multi-Dimensional Momentum ---
    # Overall (e.g. 50 rounds)
    all_nums_recent = history_df['top_3'].str.cat() + history_df['bottom_2'].str.cat()
    freq = {str(i): all_nums_recent.count(str(i)) for i in range(10)} if pd.notna(all_nums_recent) else {str(i):0 for i in range(10)}
    sorted_freq = sorted(freq.items(), key=lambda item: item[1], reverse=True)
    hot = [item[0] for item in sorted_freq]
    if len(hot) < 10:
        hot = [str(i) for i in range(10)]
        
    # Short-term (15 rounds)
    short_df = history_df.head(15)
    short_nums = short_df['top_3'].str.cat() + short_df['bottom_2'].str.cat()
    short_freq = {str(i): short_nums.count(str(i)) for i in range(10)} if pd.notna(short_nums) else freq
    short_hot = sorted(short_freq.items(), key=lambda item: item[1], reverse=True)
    s_hot = [item[0] for item in short_hot]
    if len(s_hot) < 10:
        s_hot = hot

    # --- 2. Pattern Trapping (Doubles/Siblings) ---
    # Check if last 10 rounds had any doubles in 2-digit bottom
    recent_10 = history_df.head(10)
    has_double = False
    if not recent_10.empty:
        for b in recent_10['bottom_2'].dropna():
            b_str = str(b).zfill(2)
            if len(b_str) == 2 and b_str[0] == b_str[1]:
                has_double = True
                break
            
    # Calculate Formulas
    last_top3 = str(history_df.iloc[0]['top_3']).zfill(3) if not pd.isna(history_df.iloc[0]['top_3']) else '123'
    last_bot2 = str(history_df.iloc[0]['bottom_2']).zfill(2) if not pd.isna(history_df.iloc[0]['bottom_2']) else '12'
    try:
        h, t, u = int(last_top3[0]), int(last_top3[1]), int(last_top3[2])
        formula_1 = str((h + t + u) % 10)
        formula_2 = str((int(formula_1) + 3) % 10)
    except:
        formula_1, formula_2 = '1', '8'
        
    # --- 3. Primary Signal (วิ่ง/รูด) ---
    # Strongest short term momentum + Formula 1
    pred_run = []
    pred_run.append(s_hot[0])
    if formula_1 not in pred_run:
        pred_run.append(formula_1)
    else:
        pred_run.append(s_hot[1])
        
    # --- 4. Portfolio Matrix 5-Grid (วิน 5 ตัว) ---
    # Safe combination: Short-term Hot #1, #2, Formula 1, Formula 2, and Overall Hot #1
    candidates_win = [s_hot[0], s_hot[1], formula_1, formula_2, hot[0], hot[1], s_hot[2]]
    win_unique = []
    for w in candidates_win:
        if w not in win_unique: win_unique.append(w)
        if len(win_unique) == 5: break
    while len(win_unique) < 5:
        for i in range(10):
            if str(i) not in win_unique:
                win_unique.append(str(i))
            if len(win_unique) == 5: break
            
    # --- 5. 2B (2ตัวล่าง) ---
    raw_pred_2 = [
        f"{s_hot[0]}{formula_1}",
        f"{formula_1}{formula_2}",
        f"{s_hot[1]}{s_hot[2]}",
        f"{s_hot[0]}{last_bot2[-1]}",
        f"{hot[0]}{formula_2}"
    ]
    # Trap missing double if needed
    if not has_double:
        raw_pred_2.insert(0, f"{s_hot[0]}{s_hot[0]}") # Insert a double at the top
    else:
        raw_pred_2.insert(0, f"{s_hot[0]}{s_hot[1]}")
        
    pred_2 = []
    for p in raw_pred_2:
        if p not in pred_2: pred_2.append(p)
        if len(pred_2) == 5: break
        
    # Pad pred_2 to ensure it has exactly 5 items
    idx = 0
    while len(pred_2) < 5:
        p = f"{s_hot[idx%len(s_hot)]}{hot[idx%len(hot)]}"
        if p not in pred_2: pred_2.append(p)
        idx += 1
        
    # --- 6. 3T (3ตัวบน) - Now using a 5-Digit Matrix ---
    candidates_3 = [s_hot[0], formula_1, s_hot[1], formula_2, hot[0], hot[1], s_hot[2]]
    pred_3 = []
    for p in candidates_3:
        if p not in pred_3: pred_3.append(p)
        if len(pred_3) == 5: break
        
    # Pad pred_3 to ensure it has exactly 5 items
    idx = 0
    while len(pred_3) < 5:
        p = str(idx)
        if p not in pred_3: pred_3.append(p)
        idx += 1
        
    return pred_3, pred_2, pred_run, win_unique

# --- แท็บ 3: Trend Forecast ---
if st.session_state.active_tab == "🔮 Trend Forecast":
    st.markdown("#### Predictive Asset Modeling")
    
    docs = db.collection('algo_stats').stream()
    data = [d.to_dict() for d in docs]
    algo_df = pd.DataFrame(data)
    
    # คำนวณ Win Rate (อัตราชนะ)
    algo_df['win_rate'] = algo_df.apply(lambda row: (row['wins'] / (row['wins'] + row['losses']) * 100) if (row['wins'] + row['losses']) > 0 else 0, axis=1)
    algo_df = algo_df.sort_values(by=['win_rate', 'score'], ascending=[False, False]).reset_index(drop=True)
    
    # ดึงข้อมูลทั้งหมดของเว็บนี้มาใช้วิเคราะห์
    docs = db.collection('results').where('web_name', '==', web_name).stream()
    data = [d.to_dict() for d in docs]
    df = pd.DataFrame(data)
    if not df.empty:
        df = df.sort_values(by=['date', 'round_number'], ascending=[False, False])
    
    if df.empty:
        st.warning("⚠️ กรุณาบันทึกข้อมูลผลรางวัลอย่างน้อย 1-2 รอบ เพื่อให้ระบบมีข้อมูลตั้งต้นในการวิเคราะห์")
    else:

        
        recent_rounds = df.head(50) # ดึงข้อมูล 50 รอบล่าสุดมาคำนวณ
        pred_3, pred_2, pred_run, pred_win = get_predictions(recent_rounds)
        
        # 🌟 UI ส่วนทำนาย (Custom CSS)
        next_round_guess = int(recent_rounds.iloc[0]['round_number']) + 1 if not recent_rounds.empty else 1
        if next_round_guess > 264:
            next_round_guess = 1
            
        html_code = f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Kanit:wght@400;600;800&display=swap');
        .oracle-card-wrapper {{
            background: linear-gradient(135deg, #1aa5a8, #50c9c3);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.15);
            font-family: 'Kanit', sans-serif;
            color: white;
            text-align: center;
            margin-bottom: 25px;
            position: relative;
            overflow: hidden;
        }}
        .oracle-card-wrapper::before {{
            content: ''; position: absolute; top: -50px; left: -50px; width: 150px; height: 150px;
            background: rgba(255,255,255,0.1); border-radius: 50%;
        }}
        .oracle-card-wrapper::after {{
            content: ''; position: absolute; bottom: -50px; right: -50px; width: 200px; height: 200px;
            background: rgba(255,255,255,0.1); border-radius: 50%;
        }}
        .oracle-title {{
            font-size: 28px; font-weight: 800; margin-bottom: 20px; 
            background: linear-gradient(135deg, #FFD700, #B8860B, #2C3E50, #000000);
            color: #FFF; text-shadow: 1px 1px 3px rgba(0,0,0,0.8);
            display: inline-block; padding: 6px 30px;
            border-radius: 30px; position: relative; z-index: 1;
            border: 2px solid #FFD700; box-shadow: 0 4px 10px rgba(0,0,0,0.4);
            letter-spacing: 2px;
        }}
        .prediction-container {{
            display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; position: relative; z-index: 1;
        }}
        .main-box {{
            background: rgba(255, 255, 255, 0.95); border-radius: 15px; padding: 12px 10px;
            flex: 1 1 250px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        .box-header {{
            background-color: #1aa5a8; color: white; border-radius: 20px; padding: 3px 12px;
            display: inline-block; font-weight: 600; font-size: 13px; margin-bottom: 8px;
        }}
        .box-main-number {{
            color: #2D3748; font-size: 40px; font-weight: 800; letter-spacing: 6px;
            line-height: 1.1; margin-bottom: 5px;
        }}
        .sub-numbers-container {{
            display: flex; gap: 8px; margin-top: 15px; justify-content: center;
        }}
        .sub-number {{
            background-color: #EDF2F7; color: #4A5568; padding: 6px 3px; border-radius: 10px;
            font-weight: 800; font-size: 16px; flex: 1; letter-spacing: 1px; border: 1px solid #E2E8F0;
        }}
        </style>
        <div class="oracle-card-wrapper">
            <div class="oracle-title">{next_round_guess}</div>
            <div class="prediction-container">
                <div class="main-box">
                    <div class="box-header">3 ตัวบน (วิน 5 ตัว)</div>
                    <div class="sub-numbers-container" style="margin-top: 15px; margin-bottom: 20px;">
                        <div class="sub-number" style="font-size: 26px; color: #1aa5a8; background: #fff;">{pred_3[0]}</div>
                        <div class="sub-number" style="font-size: 26px; color: #1aa5a8; background: #fff;">{pred_3[1]}</div>
                        <div class="sub-number" style="font-size: 26px; color: #1aa5a8; background: #fff;">{pred_3[2]}</div>
                        <div class="sub-number" style="font-size: 26px; color: #1aa5a8; background: #fff;">{pred_3[3]}</div>
                        <div class="sub-number" style="font-size: 26px; color: #1aa5a8; background: #fff;">{pred_3[4]}</div>
                    </div>
                    <div style="font-size: 11px; color: #1aa5a8; text-align: center;">
                        🎯 จับวิน 3 ตัวบน (นำ 5 ตัวนี้มาสลับกัน)
                    </div>
                </div>
                <div class="main-box">
                    <div class="box-header">2 ตัวล่าง</div>
                    <div class="box-main-number">{pred_2[0]}</div>
                    <div class="sub-numbers-container">
                        <div class="sub-number">{pred_2[1]}</div>
                        <div class="sub-number">{pred_2[2]}</div>
                        <div class="sub-number">{pred_2[3]}</div>
                        <div class="sub-number">{pred_2[4]}</div>
                    </div>
                </div>
            </div>
            <div class="prediction-container" style="margin-top: 15px;">
                <div class="main-box" style="flex: 1 1 150px; background: rgba(255, 245, 230, 0.95);">
                    <div class="box-header" style="background-color: #e67e22;">วิ่ง / รูด</div>
                    <div class="box-main-number" style="font-size: 30px; color: #d35400;">{pred_run[0]} <span style="font-size: 14px; color: #95a5a6; font-weight: 600;">Sec.</span> <span style="font-size: 20px; color: #e67e22;">{pred_run[1]}</span></div>
                    <div style="font-size: 11px; color: #d35400; margin-top: 10px; text-align: center;">
                        🎯 รูด {pred_run[0]} และ {pred_run[1]} ล่างกันทุน
                    </div>
                </div>
                <div class="main-box" style="flex: 1 1 250px; background: rgba(230, 245, 255, 0.95);">
                    <div class="box-header" style="background-color: #2980b9;">วิน 5 ตัว</div>
                    <div class="sub-numbers-container" style="margin-top: 5px;">
                        <div class="sub-number" style="background-color: #fff; color: #2980b9; font-size: 20px;">{pred_win[0]}</div>
                        <div class="sub-number" style="background-color: #fff; color: #2980b9; font-size: 20px;">{pred_win[1]}</div>
                        <div class="sub-number" style="background-color: #fff; color: #2980b9; font-size: 20px;">{pred_win[2]}</div>
                        <div class="sub-number" style="background-color: #fff; color: #2980b9; font-size: 20px;">{pred_win[3]}</div>
                        <div class="sub-number" style="background-color: #fff; color: #2980b9; font-size: 20px;">{pred_win[4]}</div>
                    </div>
                    <div style="font-size: 11px; color: #2980b9; margin-top: 10px; text-align: center;">
                        🎯 จับคู่วิน 5 ตัวบน-ล่าง (25 คู่) ลดเสี่ยงสูงสุด<br>
                        🔥 กระแสเลข {pred_win[0]} และ {pred_win[1]} มาแรงใน 15 รอบล่าสุด
                    </div>
                </div>
            </div>
        </div>
        """
        st.markdown(html_code, unsafe_allow_html=True)
            
        st.markdown("---")
        
        # ---- 📊 ประวัติความแม่นยำ (Accuracy Log) ----
        st.markdown("#### 📊 บันทึกประวัติแต่ละรอบ")
        
        if 'log_page' not in st.session_state:
            st.session_state.log_page = 0
            
        total_logs = len(df) - 1 # ต้องมีรอบก่อนหน้าให้ใช้อ้างอิง
        items_per_page = 10
        
        if total_logs > 0:
            start_idx = st.session_state.log_page * items_per_page
            end_idx = min(start_idx + items_per_page, total_logs)
            
            for i in range(start_idx, end_idx):
                curr = df.iloc[i]
                rnd = curr['round_number']
                act_3 = str(curr['top_3']).zfill(3)
                act_2 = str(curr['bottom_2']).zfill(2)
                
                # ดึงข้อมูลก่อนรอบนั้นเพื่อสร้างคำทำนาย
                past_df = df.iloc[i+1 : i+51]
                if not past_df.empty:
                    p3, p2, prun, pwin = get_predictions(past_df)
                    
                    # เช็กผล 3 ตัวบน (ดูว่าผล 3 ตัวบนทุกตัวเลข อยู่ในเซ็ต 5 ตัวที่ให้มาหรือไม่)
                    hit_3 = "✅" if all(d in p3 for d in act_3) else "❌"
                    hit_2 = "✅" if act_2 in p2 else "❌"
                    
                    # วิ่ง: ถ้ามีเลขใน prun ปรากฏใน act_3 หรือ act_2
                    hit_run = "✅" if any(r in act_3 for r in prun) or any(r in act_2 for r in prun) else "❌"
                    
                    # วิน 5 ตัว: ถ้านำเลขวินมาจับคู่ 2 ตัว แล้วตรงกับ 2 ตัวล่าง หรือ 2 ตัวท้ายของบน
                    is_win_bot = all(d in pwin for d in act_2)
                    is_win_top = all(d in pwin for d in act_3[-2:])
                    hit_win = "✅" if is_win_top or is_win_bot else "❌"
                    
                    st.markdown(f"**รอบ {rnd}** | ผลจริง: **{act_3} - {act_2}**  \n↳ [3 ตัว: {hit_3}] · [2 ตัว: {hit_2}] · [วิ่ง/รูด: {hit_run}] · [วิน 5 ตัว: {hit_win}]")
            
            # ปุ่มเปลี่ยนหน้า
            total_pages = (total_logs + items_per_page - 1) // items_per_page
            st.write("")
            col_prev, col_page, col_next = st.columns([1, 2, 1])
            with col_prev:
                if st.session_state.log_page > 0:
                    if st.button("⬅️ ก่อนหน้า", use_container_width=True):
                        st.session_state.log_page -= 1
                        st.rerun()
            with col_page:
                st.markdown(f"<div style='text-align: center; color: #7f8c8d; font-size: 14px;'>หน้าที่ {st.session_state.log_page + 1} / {total_pages}</div>", unsafe_allow_html=True)
            with col_next:
                if end_idx < total_logs:
                    if st.button("ถัดไป ➡️", use_container_width=True):
                        st.session_state.log_page += 1
                        st.rerun()
        else:
            st.caption("ยังไม่มีข้อมูลเพียงพอสำหรับแสดงประวัติความแม่นยำ")
            
        st.markdown("---")
        
        # ---- 📝 ฟอร์มกรอกผลจริง (Quick Record) ----
        st.markdown("#### 📝 Real-time Market Data Entry")
        st.caption("Update data to refine the predictive model in real-time.")
        
        with st.form("quick_record_form", clear_on_submit=True):
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                form_round = st.number_input("รอบที่", min_value=1, max_value=264, value=next_round_guess)
            with col_f2:
                form_top3 = st.text_input("3 ตัวบน", max_chars=3)
            with col_f3:
                form_bot2 = st.text_input("2 ตัวล่าง", max_chars=2)
                
            submit_quick = st.form_submit_button("💾 บันทึกผลรอบนี้เข้าฐานข้อมูล")
            
            if submit_quick:
                if len(form_top3) == 3 and len(form_bot2) == 2 and form_top3.isdigit() and form_bot2.isdigit():
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    if save_result(web_name, today_str, form_round, form_top3, form_bot2):
                        st.success(f"✅ บันทึกรอบ {form_round} สำเร็จ! ข้อมูลถูกอัปเดตแล้ว กรุณารีเฟรชหน้าเว็บเพื่อดูทำนายรอบถัดไป")
                        st.session_state.check_win_round = form_round
                        st.session_state.check_win_top3 = form_top3
                        st.session_state.check_win_bot2 = form_bot2
                else:
                    st.error("❌ กรุณากรอกเลข 3 ตัวบน (3 หลัก) และ 2 ตัวล่าง (2 หลัก) ให้ครบถ้วน")


# --- Notification System (ตรวจสอบการถูกรางวัลเมื่อเพิ่งบันทึก) ---
if st.session_state.get('check_win_round') is not None:
    r_num = int(st.session_state.check_win_round)
    act_3 = st.session_state.check_win_top3
    act_2 = st.session_state.check_win_bot2
    
    conn = sqlite3.connect('oracle.db')
    past_df = pd.read_sql_query('SELECT date, round_number, top_3, bottom_2 FROM results WHERE web_name = ? AND round_number < ? ORDER BY date DESC, round_number DESC LIMIT 50', conn, params=(web_name, r_num))
    conn.close()
    
    if not past_df.empty:
        p3, p2, prun, pwin = get_predictions(past_df)
        
        hits = []
        if play_run:
            run_hit_count = 0
            for r in prun:
                run_hit_count += act_3.count(r)
                if r in act_2:
                    run_hit_count += 1
            if run_hit_count > 0:
                hits.append(f"🏃 วิ่ง/รูด (เข้าเป้า {run_hit_count} เด้ง!)")
                
        if play_win5:
            is_win_bot = all(d in pwin for d in act_2)
            is_win_top = all(d in pwin for d in act_3[-2:])
            if is_win_bot and is_win_top:
                hits.append("🎯 วิน 5 ตัว (เข้าเป้า 2 เด้ง! บน-ล่าง)")
            elif is_win_bot:
                hits.append("🎯 วิน 5 ตัว (เข้าเป้า 2 ตัวล่าง!)")
            elif is_win_top:
                hits.append("🎯 วิน 5 ตัว (เข้าเป้า 2 ตัวบน!)")
                
        if play_win3 and all(d in p3 for d in act_3):
            hits.append("🎯 วิน 3 ตัวบน (แตก 3 ตัวตรง/โต๊ด!)")
            
        if play_2bot and act_2 in p2:
            hits.append("🎯 2 ตัวล่างเจาะ (เข้าเป้าตรงๆ!)")
            
        if hits:
            st.balloons()
            st.success(f"🎉 **ยินดีด้วย!! คุณถูกรางวัลรอบที่ {r_num}**\n\n" + "\n".join([f"- {h}" for h in hits]))
        else:
            st.info(f"❌ รอบที่ {r_num} พลาดไปนิดเดียว ลุยใหม่รอบหน้าครับ!")
            
    st.session_state.check_win_round = None


