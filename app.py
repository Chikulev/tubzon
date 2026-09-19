import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import calendar
import numpy as np

import urllib.parse
import streamlit.components.v1 as components

# Словари месяцев вынесены на глобальный уровень для безопасного доступа отовсюду
ru_months_nom = {1:'Январь', 2:'Февраль', 3:'Март', 4:'Апрель', 5:'Май', 6:'Июнь', 7:'Июль', 8:'Август', 9:'Сентябрь', 10:'Октябрь', 11:'Ноябрь', 12:'Декабрь'}
ru_months_dat = {1:'январю', 2:'февралю', 3:'марту', 4:'апрелю', 5:'маю', 6:'июню', 7:'июлю', 8:'августу', 9:'сентябрю', 10:'октябрю', 11:'ноябрю', 12:'декабрю'}

# Изолированные хелперы для безопасного форматирования чисел (никаких глобальных .replace() для текста)
def fmt_money(val):
    return f"{val:,.0f} ₽".replace(',', ' ')

def fmt_num(val):
    return f"{val:,.0f}".replace(',', ' ')

# --- 1. КОНФИГУРАЦИЯ И ЧИСТЫЙ СИСТЕМНЫЙ CSS ---
st.set_page_config(page_title="Dwin Home | OS", page_icon="🐺", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    header { visibility: hidden !important; }
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; }
    .stApp { background-color: #F8F9FA; color: #111827; } 
    .kpi-card { 
        background-color: #FFFFFF; 
        border-left: 5px solid #005BFF; 
        padding: 1.5rem; 
        border-radius: 0.5rem; 
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); 
        margin-bottom: 1rem;
        border: 1px solid #E5E7EB;
    }
    .kpi-title { color: #6B7280; font-size: 0.85rem; font-weight: 700; text-transform: uppercase; margin-bottom: 0.5rem; }
    .kpi-value { color: #111827; font-size: 2.2rem; font-weight: 800; }
    hr { border-color: #E5E7EB; margin: 2rem 0; }
    </style>
""", unsafe_allow_html=True)

st.title("🐺 DWINA: аналитика и прогноз")

# ГЛОБАЛЬНЫЕ НАСТРОЙКИ ГРАФИКОВ (Отключение кнопок)
PLOT_CONFIG = {'displayModeBar': False, 'staticPlot': False, 'scrollZoom': False, 'doubleClick': False, 'showTips': False}

# --- 2. ЗАГРУЗКА И ЖЕСТКАЯ ПРИВЯЗКА ФАЙЛОВ ---
c1, c2 = st.columns(2)
fbo_file = c1.file_uploader("📦 Загрузить ФБО (orders.csv)", type=["csv"])
fbs_file = c2.file_uploader("🏠 Загрузить ФБС (postings.csv)", type=["csv"])

@st.cache_data
def process_data(file, source):
    if not file: return pd.DataFrame()
    try:
        df = pd.read_csv(file, sep=None, engine='python')
        df.rename(columns=lambda x: str(x).strip('\ufeff"').strip(), inplace=True)
        
        # Ранний выход (Пункт 3)
        req_cols = ['Принят в обработку', 'Номер заказа']
        if not all(col in df.columns for col in req_cols):
            st.error(f"В файле {source} отсутствуют обязательные колонки: {', '.join(req_cols)}")
            return pd.DataFrame()
            
        df['Time_Full'] = pd.to_datetime(df['Принят в обработку'], errors='coerce')
        df.dropna(subset=['Time_Full'], inplace=True)
        df['Дата'] = df['Time_Full'].dt.normalize()
        df['Месяц'] = df['Time_Full'].dt.to_period('M').astype(str)
        df['Час'] = df['Time_Full'].dt.hour
        df['День_Недели'] = df['Time_Full'].dt.day_name()
            
        # Безопасный парсинг без скаляров (Пункт 2)
        rev = df.get('Сумма отправления')
        df['Выручка'] = pd.to_numeric(rev, errors='coerce').fillna(0) if rev is not None else 0.0
        
        qty = df.get('Количество')
        df['Штуки'] = pd.to_numeric(qty, errors='coerce').fillna(0) if qty is not None else 0.0
        
        df['Логистика'] = source
        
        # Умный парсинг Client_ID (Пункт 7)
        if source == "FBO (Склады)":
            df['Client_ID'] = df['Номер заказа'].astype(str).apply(lambda x: x.split('-')[0])
        else:
            # Для FBS отрезаем только последний суффикс, сохраняя уникальность вида 98-XXXXX
            df['Client_ID'] = df['Номер заказа'].astype(str).apply(lambda x: x.rsplit('-', 1)[0] if '-' in x else x)
            
        if 'Название товара' in df.columns:
            df['Тип_Чехла'] = df['Название товара'].apply(lambda x: str(x).split('для')[0].strip() if pd.notna(x) else 'Неизвестно')
            
        return df
    except Exception as e:
        st.error(f"Ошибка парсинга {source}: {e}")
        return pd.DataFrame()

df_fbo = process_data(fbo_file, "FBO")
df_fbs = process_data(fbs_file, "FBS")

if not df_fbo.empty or not df_fbs.empty:
    df = pd.concat([df_fbo, df_fbs], ignore_index=True)
    
    total_rev = df['Выручка'].sum()
    total_items = df['Штуки'].sum()
    total_orders = df['Номер заказа'].nunique()

    # --- 2.5 СИНХРОНИЗИРОВАННЫЕ РАСЧЕТЫ (Единый источник истины) ---
    max_date_full = df['Time_Full'].max()
    curr_month_str = max_date_full.strftime('%Y-%m')
    last_update_str = max_date_full.strftime('%d.%m.%Y в %H:%M')

    unique_months = sorted(df['Месяц'].unique())
    curr_month_df = df[df['Месяц'] == curr_month_str]
    curr_rev = curr_month_df['Выручка'].sum()
    curr_items = curr_month_df['Штуки'].sum()
    prev_rev = df[df['Месяц'] == unique_months[-2]]['Выручка'].sum() if len(unique_months) > 1 else 0

    # Прогноз: взвешиваем по среднему чеку последних 7 дней (Пункт 5)
    last_7_days = max_date_full.normalize() - pd.Timedelta(days=7)
    recent_7d_df = df[df['Time_Full'] >= last_7_days]
    run_rate_rev = recent_7d_df['Выручка'].sum() / 7 if not recent_7d_df.empty else 0
    run_rate_items = recent_7d_df['Штуки'].sum() / 7 if not recent_7d_df.empty else 0
    
    days_in_month = calendar.monthrange(max_date_full.year, max_date_full.month)[1]
    remaining_days = days_in_month - max_date_full.day
    forecast_rev = curr_rev + (run_rate_rev * remaining_days)
    forecast_items = curr_items + (run_rate_items * remaining_days)

    # Тексты (без бессмысленных долей, с безопасным форматированием через хелперы)
    short_stats = (
        f"📊 DWINA | Сводка\n"
        f"Всего: {fmt_money(total_rev)} ({fmt_num(total_items)} шт.)\n"
        f"За {curr_month_str}: {fmt_money(curr_rev)}\n"
        f"План до конца месяца: ~{fmt_money(forecast_rev)}\n"
        f"Прошлый месяц: {fmt_money(prev_rev)}\n"
        f"Актуально на: {last_update_str}"
    )

    full_stats = (
        f"🐺 DWINA | Полная аналитика\n"
        f"Актуально на: {last_update_str}\n\n"
        f"📦 ГЛОБАЛЬНО:\n"
        f"• Выручка: {fmt_money(total_rev)}\n"
        f"• Продано: {fmt_num(total_items)} шт.\n"
        f"• Заказов: {fmt_num(total_orders)}\n\n"
        f"🎯 ТЕКУЩИЙ МЕСЯЦ ({curr_month_str}):\n"
        f"• Факт: {fmt_money(curr_rev)} ({fmt_num(curr_items)} шт.)\n"
        f"• Прогноз: ~{fmt_money(forecast_rev)} (~{fmt_num(forecast_items)} шт.)\n\n"
        f"🕒 ПРОШЛЫЙ МЕСЯЦ:\n"
        f"• Факт: {fmt_money(prev_rev)}\n\n"
        f"🌐 dwina.ru"
    )

    # Отрисовка шапки
    head_c1, head_c2 = st.columns([8.5, 1.5], vertical_alignment="center")
    with head_c1:
        st.markdown(
            f"<span style='font-size: 1.05rem; color: #374151;'>"
            f"🟢 <b>Актуально на:</b> {last_update_str} &nbsp;|&nbsp; "
            f"🎯 <b>План месяца:</b> <span style='color: #10B981;'>~{fmt_money(forecast_rev)}</span> &nbsp;|&nbsp; "
            f"🕒 <b>Прошлый месяц:</b> {fmt_money(prev_rev)}"
            f"</span>", 
            unsafe_allow_html=True
        )
    with head_c2:
        with st.popover("📋 Копировать", use_container_width=True):
            st.caption("Кратко:")
            st.code(short_stats, language="markdown")
            st.caption("Полностью:")
            st.code(full_stats, language="markdown")
            
    st.markdown("<hr style='margin: 1rem 0 2rem 0;'>", unsafe_allow_html=True)
    
    # --- 3. ГЛОБАЛЬНЫЕ KPI ---
    st.markdown(f"""
        <div style="display: flex; gap: 20px; flex-wrap: wrap;">
            <div class="kpi-card" style="flex: 1; min-width: 200px;">
                <div class="kpi-title">Общая выручка</div>
                <div class="kpi-value">{total_rev:,.0f} ₽</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 200px; border-left-color: #005BFF;">
                <div class="kpi-title">Всего заказов</div>
                <div class="kpi-value">{total_orders:,.0f}</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 200px; border-left-color: #10B981;">
                <div class="kpi-title">Продано штук</div>
                <div class="kpi-value">{total_items:,.0f}</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 200px; border-left-color: #8B5CF6;">
                <div class="kpi-title">Средний чек</div>
                <div class="kpi-value">{total_rev/total_orders if total_orders else 0:,.0f} ₽</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("<hr>", unsafe_allow_html=True)

    # --- 4. МЕСЯЧНЫЙ ГРАФИК ---
    st.markdown("### 🎯 Выручка по месяцам")
    
    ru_months_nom = {1:'Январь', 2:'Февраль', 3:'Март', 4:'Апрель', 5:'Май', 6:'Июнь', 7:'Июль', 8:'Август', 9:'Сентябрь', 10:'Октябрь', 11:'Ноябрь', 12:'Декабрь'}
    ru_months_dat = {1:'январю', 2:'февралю', 3:'марту', 4:'апрелю', 5:'маю', 6:'июню', 7:'июлю', 8:'августу', 9:'сентябрю', 10:'октябрю', 11:'ноябрю', 12:'декабрю'}
    
    max_date_full = df['Time_Full'].max()
    curr_month_str = max_date_full.strftime('%Y-%m')
    elapsed_days = max_date_full.day
    days_in_curr_month = calendar.monthrange(max_date_full.year, max_date_full.month)[1]
    
    monthly_data = []
    unique_months = sorted(df['Месяц'].unique())
    
    def format_diff(curr, prev, is_money=True):
        if prev == 0: return ""
        diff = curr - prev
        pct = (diff / prev) * 100
        sign = "+" if diff > 0 else ""
        unit = " ₽" if is_money else " шт."
        color = "#10B981" if diff > 0 else "#EF4444"
        val_str = f"{diff:,.0f}".replace(',', ' ')
        return f"(<span style='color:{color}'>{sign}{val_str}{unit} | {sign}{pct:.1f}%</span>)"

    for i, m_str in enumerate(unique_months):
        m_df = df[df['Месяц'] == m_str]
        m_num = int(m_str.split('-')[1])
        m_name = ru_months_nom[m_num]
        
        m_rev = m_df['Выручка'].sum()
        m_items = m_df['Штуки'].sum()
        m_fbo_rev = m_df[m_df['Логистика'] == 'FBO']['Выручка'].sum()
        m_fbo_items = m_df[m_df['Логистика'] == 'FBO']['Штуки'].sum()
        m_fbs_rev = m_df[m_df['Логистика'] == 'FBS']['Выручка'].sum()
        m_fbs_items = m_df[m_df['Логистика'] == 'FBS']['Штуки'].sum()
        
        prev_m_str = unique_months[i-1] if i > 0 else None
        prev_name_dat = ru_months_dat[int(prev_m_str.split('-')[1])] if prev_m_str else "прошлому месяцу"
        
        if m_str == curr_month_str:
            if prev_m_str:
                df_prev_same = df[(df['Месяц'] == prev_m_str) & (df['Time_Full'].dt.day <= elapsed_days)]
                p_rev = df_prev_same['Выручка'].sum()
                p_items = df_prev_same['Штуки'].sum()
                p_fbs_rev = df_prev_same[df_prev_same['Логистика'] == 'FBS (Дом)']['Выручка'].sum()
                p_fbo_rev = df_prev_same[df_prev_same['Логистика'] == 'FBO (Склады)']['Выручка'].sum()
            else:
                p_rev = p_items = p_fbs_rev = p_fbo_rev = 0
            
            multiplier = days_in_curr_month / elapsed_days if elapsed_days > 0 else 1
            proj_rev = m_rev * multiplier
            proj_items = m_items * multiplier
            
            hover_text = (
                f"<b style='font-size: 14px;'>{m_name.upper()} (Аналитика за первые {elapsed_days} дн.)</b><br><br>"
                f"Всего сейчас: <b>{m_rev:,.0f} ₽</b> {format_diff(m_rev, p_rev, True)} к {prev_name_dat}<br>"
                f"Всего сейчас: <b>{m_items:.0f} шт.</b> {format_diff(m_items, p_items, False)} к {prev_name_dat}<br><br>"
                f"ФБС сейчас: {m_fbs_items:.0f} шт., <b>{m_fbs_rev:,.0f} ₽</b> {format_diff(m_fbs_rev, p_fbs_rev, True)}<br>"
                f"ФБО сейчас: {m_fbo_items:.0f} шт., <b>{m_fbo_rev:,.0f} ₽</b> {format_diff(m_fbo_rev, p_fbo_rev, True)}<br><br>"
                f"<b>ПРОГНОЗ за ВЕСЬ {m_name.upper()} (прошло {elapsed_days} дн., осталось {days_in_curr_month - elapsed_days}):</b><br>"
                f"Ожидаем всего: ~{proj_rev:,.0f} ₽ | ~{proj_items:.0f} шт."
            )
        else:
            if prev_m_str:
                df_prev = df[df['Месяц'] == prev_m_str]
                p_rev = df_prev['Выручка'].sum()
                p_items = df_prev['Штуки'].sum()
                p_fbs_rev = df_prev[df_prev['Логистика'] == 'FBS']['Выручка'].sum()
                p_fbo_rev = df_prev[df_prev['Логистика'] == 'FBO']['Выручка'].sum()
            else:
                p_rev = p_items = p_fbs_rev = p_fbo_rev = 0
                
            hover_text = (
                f"<b style='font-size: 14px;'>{m_name.upper()} (Итоги месяца)</b><br><br>"
                f"Всего: <b>{m_rev:,.0f} ₽</b> {format_diff(m_rev, p_rev, True)} к {prev_name_dat}<br>"
                f"Всего: <b>{m_items:.0f} шт.</b> {format_diff(m_items, p_items, False)} к {prev_name_dat}<br><br>"
                f"ФБС: {m_fbs_items:.0f} шт., <b>{m_fbs_rev:,.0f} ₽</b> {format_diff(m_fbs_rev, p_fbs_rev, True)}<br>"
                f"ФБО: {m_fbo_items:.0f} шт., <b>{m_fbo_rev:,.0f} ₽</b> {format_diff(m_fbo_rev, p_fbo_rev, True)}"
            )
            
        monthly_data.append({'Месяц': m_name, 'ФБС_Выручка': m_fbs_rev, 'ФБО_Выручка': m_fbo_rev, 'Hover': hover_text})
        
    df_monthly_viz = pd.DataFrame(monthly_data)
    
    fig_monthly = go.Figure()
    fig_monthly.add_trace(go.Bar(x=df_monthly_viz['Месяц'], y=df_monthly_viz['ФБС_Выручка'], name='ФБС', marker_color='#FF5C00', customdata=df_monthly_viz['Hover'], hovertemplate="%{customdata}<extra></extra>"))
    fig_monthly.add_trace(go.Bar(x=df_monthly_viz['Месяц'], y=df_monthly_viz['ФБО_Выручка'], name='ФБО', marker_color='#005BFF', customdata=df_monthly_viz['Hover'], hovertemplate="%{customdata}<extra></extra>"))
    
    fig_monthly.update_layout(
        barmode='stack', hovermode='closest', 
        hoverlabel=dict(bgcolor="white", font_size=13, bordercolor="#E5E7EB"),
        plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'),
        margin=dict(t=10, b=0, l=0, r=0), height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig_monthly.update_yaxes(showgrid=True, gridcolor='#E5E7EB', title="Выручка (₽)")
    st.plotly_chart(fig_monthly, use_container_width=True, config=PLOT_CONFIG)

    st.markdown("<hr>", unsafe_allow_html=True)

    # --- 5. ДИНАМИКА ПРОДАЖ ПО ДНЯМ (ФАКТ И ТРЕНД РАЗДЕЛЕНЫ) ---
    st.markdown("### 📈 Динамика продаж по дням")
    
    if 'Дата' in df.columns:
        min_date, max_date_f = df['Дата'].min(), df['Дата'].max()
        all_dates = pd.date_range(min_date, max_date_f)
        
        # 1. ФАКТИЧЕСКАЯ ВЫРУЧКА
        fbs_daily = df[df['Логистика']=="FBS (Дом)"].groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        fbo_daily = df[df['Логистика']=="FBO (Склады)"].groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        total_daily = df.groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        
        fig_sales = go.Figure()
        fig_sales.add_trace(go.Scatter(x=all_dates, y=fbs_daily, name='ФБС (Факт)', mode='lines', line=dict(color='#FF5C00', width=2)))
        fig_sales.add_trace(go.Scatter(x=all_dates, y=fbo_daily, name='ФБО (Факт)', mode='lines', line=dict(color='#005BFF', width=2)))
        fig_sales.add_trace(go.Scatter(x=all_dates, y=total_daily, name='СУММА', mode='lines', line=dict(color='#10B981', width=3, dash='dot')))
        
        fig_sales.update_layout(hovermode="x unified", plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'), margin=dict(t=10, b=10, l=0, r=0))
        fig_sales.update_xaxes(type='date', showgrid=True, gridcolor='#E5E7EB', tickformat="%d %b")
        fig_sales.update_yaxes(showgrid=True, gridcolor='#E5E7EB', title="Реальная выручка (₽)")
        st.plotly_chart(fig_sales, use_container_width=True, config=PLOT_CONFIG)
        
        # 2. ОРГАНИЧЕСКИЙ ТРЕНД (Очищено от оптовых аномалий)
        st.markdown("#### 🌊 Органический тренд (Очищено от оптовых аномалий)")
        st.write("Случайные оптовые заказы сведены к 1 средневзвешенному чеку. Показывает чистую скользящую среднюю (SMA-7) спроса.")
        
        # Корректный расчет средневзвешенной цены за визит
        daily_visits = df.groupby(['Дата', 'Client_ID']).agg({'Выручка': 'sum', 'Штуки': 'sum'}).reset_index()
        daily_visits['Цена_1_шт'] = np.where(daily_visits['Штуки'] > 0, daily_visits['Выручка'] / daily_visits['Штуки'], 0)
        
        total_organic_daily = daily_visits.groupby('Дата')['Цена_1_шт'].sum().reindex(all_dates, fill_value=0)
        trend_7d = total_organic_daily.rolling(window=7, min_periods=1).mean()
        
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=all_dates, y=trend_7d, name='SMA-7 (Органический тренд)', mode='lines', fill='tozeroy', line=dict(color='#8B5CF6', width=3), fillcolor='rgba(139, 92, 246, 0.2)'))
        fig_trend.update_layout(hovermode="x unified", plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'), margin=dict(t=10, b=10, l=0, r=0), height=300)
        fig_trend.update_xaxes(type='date', showgrid=True, gridcolor='#E5E7EB', tickformat="%d %b")
        fig_trend.update_yaxes(showgrid=True, gridcolor='#E5E7EB', title="Усредненная выручка (₽)")
        st.plotly_chart(fig_trend, use_container_width=True, config=PLOT_CONFIG)

    st.markdown("<hr>", unsafe_allow_html=True)

    # --- 6. АНАЛИТИКА АУДИТОРИИ (ПРОЦЕНТЫ И УНИКАЛЬНЫЕ ВИЗИТЫ) ---
    st.markdown("### 🔥 Прайм-тайм и Дни недели")
    col_aud1, col_aud2 = st.columns(2)
    with col_aud1:
        def categorize_time(h):
            if 6 <= h < 12: return 'Утро (06-12)'
            elif 12 <= h < 18: return 'День (12-18)'
            elif 18 <= h < 24: return 'Вечер (18-24)'
            else: return 'Ночь (00-06)'

        df['Время_Суток'] = df['Час'].apply(categorize_time)
        tod_stats = df.groupby('Время_Суток')['Client_ID'].nunique().reset_index()
        fig_pie = px.pie(tod_stats, values='Client_ID', names='Время_Суток', hole=0.5, title="По времени суток", color_discrete_sequence=px.colors.sequential.Teal)
        fig_pie.update_layout(plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'))
        st.plotly_chart(fig_pie, use_container_width=True, config=PLOT_CONFIG)
        
    with col_aud2:
        dow_map = {'Monday': 'ПН', 'Tuesday': 'ВТ', 'Wednesday': 'СР', 'Thursday': 'ЧТ', 'Friday': 'ПТ', 'Saturday': 'СБ', 'Sunday': 'ВС'}
        df['Day_RU'] = df['День_Недели'].map(dow_map)
        dow_order = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
        dow_stats = df.groupby('Day_RU')['Client_ID'].nunique().reindex(dow_order).reset_index()
        
        # Перевод в проценты
        total_visits = dow_stats['Client_ID'].sum()
        dow_stats['Percent'] = (dow_stats['Client_ID'] / total_visits) * 100
        
        fig_dow = px.bar(dow_stats, x='Day_RU', y='Percent', title="По дням недели (%)", text=dow_stats['Percent'].apply(lambda x: f"{x:.1f}%"))
        fig_dow.update_layout(plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'))
        fig_dow.update_traces(marker_color='#10B981', textposition='outside')
        fig_dow.update_yaxes(title="Доля от всех визитов (%)", showgrid=True, gridcolor='#E5E7EB')
        st.plotly_chart(fig_dow, use_container_width=True, config=PLOT_CONFIG)

    st.markdown("<hr>", unsafe_allow_html=True)

    # --- 7. ТОВАРНАЯ МАТРИЦА (ОБЪЕДИНЕНИЕ ПО АРТИКУЛУ/SKU) ---
    st.markdown("### 📦 Аналитика по товарам")
    
    group_col = 'Артикул' if 'Артикул' in df.columns else ('SKU' if 'SKU' in df.columns else 'Тип_Чехла')
    
    if group_col in df.columns:
        prod_stats = df.groupby(group_col).agg(
            Выручка=('Выручка', 'sum'),
            Штук=('Штуки', 'sum'),
            Название=('Название товара', lambda x: x.mode()[0] if not x.empty and 'Название товара' in df.columns else (x.iloc[0] if not x.empty else 'Неизвестно'))
        ).reset_index().sort_values('Выручка', ascending=False)
        
        prod_stats['Модель / Цвет'] = prod_stats['Название'].apply(lambda x: str(x).split('для')[0].strip() if pd.notna(x) else 'Неизвестно')
        prod_stats['Ср_Цена'] = (prod_stats['Выручка'] / prod_stats['Штук'].replace(0, 1)).round(0)
        prod_stats['Доля_%'] = (prod_stats['Выручка'] / total_rev * 100).round(1)
        
        st.dataframe(
            prod_stats[['Модель / Цвет', 'Выручка', 'Штук', 'Ср_Цена', 'Доля_%']],
            column_config={
                "Модель / Цвет": st.column_config.TextColumn("Модель / Цвет", width="medium"),
                "Выручка": st.column_config.ProgressColumn("Выручка (₽)", format="%d ₽", min_value=0, max_value=int(prod_stats['Выручка'].max())),
                "Штук": st.column_config.NumberColumn("Продано (шт)", format="%d"),
                "Ср_Цена": st.column_config.NumberColumn("Средняя цена", format="%d ₽"),
                "Доля_%": st.column_config.NumberColumn("Доля в обороте", format="%.1f %%")
            }, hide_index=True, use_container_width=True
        )

        # --- 7.1 БЛОК УПРАВЛЕНИЯ ЗАПАСАМИ И ДЕФИЦИТОМ (ОДНА ТАБЛИЦА) ---
        st.markdown("#### 🏭 План производства и Дефицит складов")
        st.write("Введите в колонку **«Сейчас на складе ✍️»** ваши реальные остатки. "
                 "Дефицит и статус пересчитаются автоматически на основе прогноза спроса на 30 дней.")

        days_in_data = (df['Дата'].max() - df['Дата'].min()).days + 1
        if days_in_data < 1:
            days_in_data = 1

        # Хранилище введённых остатков
        if 'stock_values' not in st.session_state:
            st.session_state.stock_values = {}

        # Базовая таблица
        deficit_df = prod_stats[['Модель / Цвет', 'Штук']].copy()
        deficit_df['Прогноз (30 дн)'] = np.ceil((deficit_df['Штук'] / days_in_data) * 30).astype(int)
        deficit_df['Сейчас на складе ✍️'] = (
            deficit_df['Модель / Цвет']
            .map(st.session_state.stock_values)
            .fillna(0)
            .astype(int)
        )
        deficit_df['Дефицит'] = deficit_df['Прогноз (30 дн)'] - deficit_df['Сейчас на складе ✍️']
        deficit_df['Статус Производства'] = deficit_df['Дефицит'].apply(
            lambda x: f"🛑 Напечатать {int(x)} шт." if x > 0 else "✅ Хватает"
        )

        # Единая таблица-редактор
        edited_deficit = st.data_editor(
            deficit_df[['Модель / Цвет', 'Прогноз (30 дн)', 'Сейчас на складе ✍️', 'Дефицит', 'Статус Производства']],
            column_config={
                "Модель / Цвет": st.column_config.TextColumn("Товар", disabled=True, width="medium"),
                "Прогноз (30 дн)": st.column_config.NumberColumn("Спрос на 30 дней", disabled=True, format="%d шт."),
                "Сейчас на складе ✍️": st.column_config.NumberColumn(
                    "Сейчас на складе ✍️", min_value=0, step=1, format="%d шт."
                ),
                "Дефицит": st.column_config.NumberColumn("Дефицит", disabled=True, format="%d шт."),
                "Статус Производства": st.column_config.TextColumn("Статус производства", disabled=True, width="medium"),
            },
            hide_index=True,
            use_container_width=True,
            key="stock_editor",
        )

        # Если пользователь поменял остатки — сохраняем и перерисовываем,
        # чтобы «Дефицит» и «Статус» пересчитались сразу же
        new_stocks = dict(zip(edited_deficit['Модель / Цвет'], edited_deficit['Сейчас на складе ✍️']))
        if new_stocks != st.session_state.stock_values:
            st.session_state.stock_values = new_stocks
            st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)

    # --- 8. LTV ---
    st.markdown("### 🤝 База возвращающихся клиентов (LTV)")
    if 'Client_ID' in df.columns:
        clients = df.groupby('Client_ID').agg(
            Визитов=('Дата', 'nunique'),
            Штук_Всего=('Штуки', 'sum'),
            Общая_Выручка=('Выручка', 'sum'),
            Даты_Заказов=('Дата', lambda x: ", ".join(sorted([d.strftime('%d.%m.%Y') for d in x.unique()])))
        ).reset_index()
        
        ltv_clients = clients[clients['Визитов'] > 1].sort_values('Общая_Выручка', ascending=False)
        st.write(f"Найдено **{len(ltv_clients)}** покупателей, которые оформили повторные заказы в другие дни.")
        if not ltv_clients.empty:
            st.dataframe(ltv_clients, hide_index=True, use_container_width=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # --- 9. ГЛОБАЛЬНАЯ ТАБЛИЦА: АРХИВ + ТЕКУЩИЙ + ПРОГНОЗ НА ГОД ---
    st.markdown("### 🧠 Таблица жизни — архив & Умный AI-Прогноз")
    st.write("Настройте юнит-экономику, чтобы рассчитать чистую прибыль в архиве и прогнозах.")
    
    col_eco1, col_eco2 = st.columns(2)
    cogs = col_eco1.number_input("Себестоимость 1 шт. (₽)", value=4.0, step=0.5)
    ozon_fee = col_eco2.slider("Доля маркетплейса (%)", 10.0, 90.0, 50.0)
    
    monthly_summary = df.groupby('Месяц').agg({'Выручка': 'sum', 'Штуки': 'sum'}).reset_index()
    fbo_agg = df[df['Логистика'] == 'FBO (Склады)'].groupby('Месяц')['Выручка'].sum().to_dict()
    fbs_agg = df[df['Логистика'] == 'FBS (Дом)'].groupby('Месяц')['Выручка'].sum().to_dict()
    
    table_data = []
    
    # АРХИВ
    for i, m_str in enumerate(unique_months):
        if m_str == curr_month_str: continue
        y, m = map(int, m_str.split('-'))
        m_name = f"{ru_months_nom[m]} {y}"
        rev = monthly_summary.loc[monthly_summary['Месяц'] == m_str, 'Выручка'].values[0]
        items = monthly_summary.loc[monthly_summary['Месяц'] == m_str, 'Штуки'].values[0]
        
        table_data.append({
            "Месяц": m_name,
            "Статус": "Архив (Факт)",
            "Выручка (₽)": rev,
            "Штук": items,
            "ФБС (₽)": fbs_agg.get(m_str, 0),
            "ФБО (₽)": fbo_agg.get(m_str, 0)
        })

    # ТЕКУЩИЙ МЕСЯЦ
    curr_rev = monthly_summary.loc[monthly_summary['Месяц'] == curr_month_str, 'Выручка'].values[0]
    curr_items = monthly_summary.loc[monthly_summary['Месяц'] == curr_month_str, 'Штуки'].values[0]
    days_in_curr = calendar.monthrange(max_date_full.year, max_date_full.month)[1]
    multiplier = days_in_curr / elapsed_days if elapsed_days > 0 else 1
    
    proj_rev = curr_rev * multiplier
    proj_items = curr_items * multiplier
    
    fbo_ratio = fbo_agg.get(curr_month_str, 0) / curr_rev if curr_rev > 0 else 0.5
    fbs_ratio = 1 - fbo_ratio
    
    table_data.append({
        "Месяц": f"{ru_months_nom[max_date_full.month]} {max_date_full.year}",
        "Статус": "Текущий (Проекция)",
        "Выручка (₽)": proj_rev,
        "Штук": proj_items,
        "ФБС (₽)": proj_rev * fbs_ratio,
        "ФБО (₽)": proj_rev * fbo_ratio
    })

    # БУДУЩИЕ МЕСЯЦЫ (AI-ПРОГНОЗ)
    hist_revs = monthly_summary.set_index('Месяц')['Выручка'].to_dict()
    hist_revs[curr_month_str] = proj_rev 
    m_keys = sorted(hist_revs.keys())
    growths = [hist_revs[m_keys[i]] / hist_revs[m_keys[i-1]] for i in range(1, len(m_keys)) if hist_revs[m_keys[i-1]] > 0]
    
    if len(growths) >= 2:
        ai_multiplier = growths[-1] * 0.7 + growths[-2] * 0.3
    elif len(growths) == 1:
        ai_multiplier = growths[0]
    else:
        ai_multiplier = 1.5
        
    run_rev = proj_rev
    run_items = proj_items
    curr_dt = max_date_full
    
    for i in range(1, 13):
        m_step = curr_dt.month - 1 + 1
        y_step = curr_dt.year + m_step // 12
        m_step = m_step % 12 + 1
        curr_dt = datetime(y_step, m_step, 1)
        
        ai_multiplier = 1.0 + ((ai_multiplier - 1.0) * 0.85)
        run_rev *= ai_multiplier
        run_items *= ai_multiplier
        
        table_data.append({
            "Месяц": f"{ru_months_nom[m_step]} {y_step}",
            "Статус": "Прогноз",
            "Выручка (₽)": run_rev,
            "Штук": run_items,
            "ФБС (₽)": run_rev * fbs_ratio,
            "ФБО (₽)": run_rev * fbo_ratio
        })

    df_table = pd.DataFrame(table_data)
    
    # Считаем сырую прибыль
    df_table['Чистая Прибыль (сырая)'] = df_table['Выручка (₽)'] - (df_table['Штук'] * cogs) - (df_table['Выручка (₽)'] * (ozon_fee/100))
    
    # Считаем процентную динамику (month-over-month)
    df_table['Динамика'] = df_table['Чистая Прибыль (сырая)'].pct_change() * 100

    # Склеиваем сумму и процент в красивую строку
    def format_profit(row):
        val = row['Чистая Прибыль (сырая)']
        diff = row['Динамика']
        val_str = fmt_money(val)
        
        if pd.isna(diff) or np.isinf(diff):
            return val_str
            
        sign = "+" if diff > 0 else ""
        return f"{val_str} ({sign}{diff:.1f}%)"
        
    df_table['Чистая Прибыль'] = df_table.apply(format_profit, axis=1)

    st.table(
        df_table,
        column_config={
            "Месяц": st.column_config.TextColumn("Месяц"),
            "Статус": st.column_config.TextColumn("Статус"),
            "Выручка (₽)": st.column_config.NumberColumn("Выручка (₽)", format="%d ₽"),
            "Штук": st.column_config.NumberColumn("Спрос (Штук)", format="%d"),
            "ФБС (₽)": st.column_config.NumberColumn("ФБС", format="%d ₽"),
            "ФБО (₽)": st.column_config.NumberColumn("ФБО", format="%d ₽"),
            "Чистая Прибыль": st.column_config.TextColumn("Чистая Прибыль")
        },
        column_order=["Месяц", "Статус", "Выручка (₽)", "Штук", "ФБС (₽)", "ФБО (₽)", "Чистая Прибыль"],
        hide_index=True, use_container_width=True
    )

else:
    st.info("👆 Загрузите выгрузки orders.csv (FBO) и postings.csv (FBS)...")