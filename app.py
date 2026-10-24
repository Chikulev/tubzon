import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import calendar
import numpy as np

# --- 1. ГЛОБАЛЬНЫЕ СЛОВАРИ, ХЕЛПЕРЫ И КОНФИГУРАЦИЯ ---
ru_months_nom = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь',
    7: 'Июль', 8: 'Август', 9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
}
ru_months_dat = {
    1: 'январю', 2: 'февралю', 3: 'марту', 4: 'апрелю', 5: 'маю', 6: 'июню',
    7: 'июлю', 8: 'августу', 9: 'сентябрю', 10: 'октябрю', 11: 'ноябрю', 12: 'декабрю'
}

def fmt_money(val):
    if pd.isna(val):
        return "0 ₽"
    return f"{val:,.0f} ₽".replace(',', ' ')

def fmt_num(val):
    if pd.isna(val):
        return "0"
    return f"{val:,.0f}".replace(',', ' ')

def format_diff(curr, prev, is_money=True):
    if prev == 0 or pd.isna(prev):
        return ""
    diff = curr - prev
    pct = (diff / prev) * 100
    sign = "+" if diff > 0 else ""
    unit = " ₽" if is_money else " шт."
    color = "#10B981" if diff > 0 else "#EF4444"
    val_str = f"{diff:,.0f}".replace(',', ' ')
    return f"(<span style='color:{color}'>{sign}{val_str}{unit} | {sign}{pct:.1f}%</span>)"

st.set_page_config(page_title="DWINA OS | Аналитика и Управление", page_icon="🐺", layout="wide", initial_sidebar_state="collapsed")

# Чистый светлый интерфейс без верхнего хедера
st.markdown("""
    <style>
    header { visibility: hidden !important; }
    .block-container { padding-top: 1rem !important; padding-bottom: 2.5rem !important; max-width: 98% !important; }
    .stApp { background-color: #F8F9FA; color: #111827; }
    .kpi-card { 
        background-color: #FFFFFF; 
        border-left: 5px solid #005BFF; 
        padding: 1.15rem 1.3rem; 
        border-radius: 0.6rem; 
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.04); 
        margin-bottom: 0.8rem;
        border: 1px solid #E5E7EB;
        border-left-width: 5px;
    }
    .kpi-title { color: #6B7280; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 0.35rem; }
    .kpi-value { color: #111827; font-size: 1.85rem; font-weight: 800; line-height: 1.15; }
    .kpi-sub { color: #6B7280; font-size: 0.8rem; margin-top: 0.35rem; font-weight: 500; }
    .insight-box {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 0.6rem;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
    }
    hr { border-color: #E5E7EB; margin: 1.5rem 0; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background-color: #FFFFFF; padding: 6px 10px; border-radius: 10px; border: 1px solid #E5E7EB; }
    .stTabs [data-baseweb="tab"] { border-radius: 6px; padding: 8px 16px; font-weight: 600; }
    </style>
""", unsafe_allow_html=True)

PLOT_CONFIG = {'displayModeBar': False, 'staticPlot': False, 'scrollZoom': False, 'doubleClick': False, 'showTips': False}

st.title("🐺 DWINA OS: Аналитика, Прогноз и Радар Роста")

# --- 2. МУЛЬТИ-ЗАГРУЗЧИК И SMART-КОМПИЛЯТОР БАЗЫ ЗАКАЗОВ (ETL) ---
c1, c2 = st.columns(2)
fbo_files = c1.file_uploader(
    "📦 Загрузить FBO (orders.csv — можно выбрать сразу несколько файлов за разные месяцы)",
    type=["csv"], accept_multiple_files=True
)
fbs_files = c2.file_uploader(
    "🏠 Загрузить FBS (postings.csv — можно выбрать сразу несколько файлов за разные месяцы)",
    type=["csv"], accept_multiple_files=True
)

STATUS_PRIORITY = {
    'Ожидает сборки': 1,
    'Ожидает отгрузки': 2,
    'Доставляется': 3,
    'Ожидает в ПВЗ': 4,
    'Условно доставлен': 5,
    'Доставлен': 6,
    'Отменён': 6
}

@st.cache_data
def compile_multiple_files(files_list, default_source):
    if not files_list:
        return pd.DataFrame(), pd.DataFrame()
    
    raw_frames = []
    audit_logs = []
    
    for idx, file_obj in enumerate(files_list):
        try:
            file_obj.seek(0)
            df_part = pd.read_csv(file_obj, sep=None, engine='python')
            df_part.rename(columns=lambda x: str(x).strip('\ufeff"').strip(), inplace=True)
            
            req_cols = ['Принят в обработку', 'Номер заказа']
            if not all(col in df_part.columns for col in req_cols):
                st.warning(f"⚠️ Пропущен файл {file_obj.name}: нет обязательных колонок Ozon.")
                continue
                
            # Автоопределение FBO vs FBS на случай, если в файл уже склеены оба типа или перепутано окно
            if 'Логистика' in df_part.columns and df_part['Логистика'].notna().any():
                detected_source = df_part['Логистика'].fillna(default_source)
            elif 'Код этикетки' in df_part.columns or 'Дата отгрузки без просрочки' in df_part.columns or 'Фактическая тарификация' in df_part.columns:
                detected_source = "FBS"
            elif 'Объект размещения' in df_part.columns or 'Доупаковка' in df_part.columns:
                detected_source = "FBO"
            else:
                detected_source = default_source
                
            df_part['Логистика'] = detected_source
            df_part['Time_Full'] = pd.to_datetime(df_part['Принят в обработку'], errors='coerce')
            df_part.dropna(subset=['Time_Full'], inplace=True)
            
            if df_part.empty:
                continue
                
            # Возраст файла определяется по самому свежему заказу внутри этого файла
            file_max_dt = df_part['Time_Full'].max()
            file_min_dt = df_part['Time_Full'].min()
            
            df_part['_file_name'] = file_obj.name
            df_part['_file_max_dt'] = file_max_dt
            df_part['_file_order'] = idx
            
            raw_frames.append(df_part)
            audit_logs.append({
                'Файл': file_obj.name,
                'Канал': detected_source if isinstance(detected_source, str) else "FBO + FBS",
                'Строк в файле': len(df_part),
                'Первый заказ': file_min_dt.strftime('%d.%m.%Y %H:%M'),
                'Последний заказ (Актуальность)': file_max_dt.strftime('%d.%m.%Y %H:%M'),
                '_sort_dt': file_max_dt
            })
        except Exception as e:
            st.error(f"Ошибка чтения файла {getattr(file_obj, 'name', 'CSV')}: {e}")
            
    if not raw_frames:
        return pd.DataFrame(), pd.DataFrame()
        
    combined = pd.concat(raw_frames, ignore_index=True)
    
    # Формируем ключ позиции: в Ozon в одном отправлении может быть несколько разных SKU (цветов)
    if 'Номер отправления' in combined.columns:
        combined['_posting_key'] = combined['Номер отправления'].astype(str).str.strip()
    else:
        combined['_posting_key'] = combined['Номер заказа'].astype(str).str.strip()
        
    if 'SKU' in combined.columns:
        combined['_sku_key'] = combined['SKU'].astype(str).str.strip()
    elif 'Артикул' in combined.columns:
        combined['_sku_key'] = combined['Артикул'].astype(str).str.strip()
    else:
        combined['_sku_key'] = combined.get('Название товара', '').astype(str)
        
    # Приоритет статуса: если заказ в старом файле был "Доставляется", а в новом стал "Доставлен" — побеждает новый
    combined['_status_rank'] = combined.get('Статус', '').map(STATUS_PRIORITY).fillna(0)
    combined['_has_delivery_dt'] = combined.get('Дата доставки', pd.Series(index=combined.index)).notna().astype(int)
    
    # Сортируем от старых к новым: последняя строка для каждого (Номер отправления, SKU) — самая актуальная
    combined.sort_values(
        by=['_file_max_dt', '_status_rank', '_has_delivery_dt', '_file_order'],
        ascending=[True, True, True, True],
        inplace=True
    )
    
    deduped = combined.drop_duplicates(subset=['_posting_key', '_sku_key'], keep='last').copy()
    
    # Обогащение и очистка колонок
    deduped['Дата'] = deduped['Time_Full'].dt.normalize()
    deduped['Месяц'] = deduped['Time_Full'].dt.to_period('M').astype(str)
    deduped['Час'] = deduped['Time_Full'].dt.hour
    deduped['День_Недели'] = deduped['Time_Full'].dt.day_name()
    
    deduped['Выручка'] = pd.to_numeric(deduped.get('Сумма отправления', 0), errors='coerce').fillna(0.0)
    deduped['Оплачено_покупателем'] = pd.to_numeric(deduped.get('Оплачено покупателем', 0), errors='coerce').fillna(0.0)
    deduped['Цена_до_скидок'] = pd.to_numeric(deduped.get('Цена товара до скидок', 0), errors='coerce').fillna(0.0)
    deduped['Штуки'] = pd.to_numeric(deduped.get('Количество', 0), errors='coerce').fillna(0.0)
    deduped['Цена_1_шт'] = np.where(deduped['Штуки'] > 0, deduped['Выручка'] / deduped['Штуки'], 0.0)
    deduped['Оплачено_за_1_шт'] = np.where(deduped['Штуки'] > 0, deduped['Оплачено_покупателем'] / deduped['Штуки'], 0.0)
    
    # Соинвест Ozon (разница между нашей выручкой и тем, что реально заплатил покупатель по Ozon Карте / СПП)
    deduped['Соинвест_Ozon'] = np.maximum(0.0, deduped['Выручка'] - deduped['Оплачено_покупателем'] * deduped['Штуки'])
    
    # Единый парсинг Client_ID (до первого тире — объединяет покупки одного человека в FBO и FBS)
    deduped['Client_ID'] = deduped['Номер заказа'].astype(str).apply(lambda x: x.split('-')[0].strip())
    
    # Даты логистики
    for dt_col in ['Дата доставки', 'Фактическая дата передачи в доставку', 'Дата отгрузки без просрочки', 'Дата отмены']:
        if dt_col in deduped.columns:
            deduped[dt_col + '_dt'] = pd.to_datetime(deduped[dt_col], errors='coerce')
            
    if 'Дата доставки_dt' in deduped.columns and 'Фактическая дата передачи в доставку_dt' in deduped.columns:
        deduped['Дней_в_пути'] = (deduped['Дата доставки_dt'] - deduped['Фактическая дата передачи в доставку_dt']).dt.total_seconds() / 86400.0
    else:
        deduped['Дней_в_пути'] = np.nan
        
    # Чистое название модели/цвета
    if 'Название товара' in deduped.columns:
        deduped['Тип_Чехла'] = deduped['Название товара'].apply(
            lambda x: str(x).split('для')[0].strip() if pd.notna(x) else 'Неизвестно'
        )
    else:
        deduped['Тип_Чехла'] = 'Неизвестно'
        
    # Классификация акций и бустинга
    def classify_promo(val):
        if pd.isna(val) or not str(val).strip():
            return "Без акций (Органика)"
        s = str(val).lower()
        if "максимальный бустинг" in s:
            return "🚀 Максимальный бустинг"
        elif "эластичный бустинг" in s:
            return "⚡ Эластичный бустинг"
        elif "акция" in s or "скидка" in s:
            return "🏷️ Только СПП / Базовая скидка"
        return "Прочие акции"
        
    deduped['Тип_Продвижения'] = deduped.get('Акции', pd.Series(index=deduped.index)).apply(classify_promo)
    
    deduped.sort_values('Time_Full', ascending=False, inplace=True)
    audit_df = pd.DataFrame(audit_logs).sort_values('_sort_dt', ascending=False).drop(columns=['_sort_dt'])
    return deduped, audit_df

df_fbo, audit_fbo = compile_multiple_files(fbo_files, "FBO")
df_fbs, audit_fbs = compile_multiple_files(fbs_files, "FBS")

if not df_fbo.empty or not df_fbs.empty:
    df_raw_all = pd.concat([df_fbo, df_fbs], ignore_index=True)
    # На случай если пользователь загрузил комбинированный мастер-файл, повторно защищаем от дублей между слотами
    df_raw_all.sort_values(by=['_file_max_dt', '_status_rank', '_has_delivery_dt'], ascending=[True, True, True], inplace=True)
    df_full = df_raw_all.drop_duplicates(subset=['_posting_key', '_sku_key'], keep='last').sort_values('Time_Full', ascending=False).reset_index(drop=True)
    
    audit_all = pd.concat([audit_fbo, audit_fbs], ignore_index=True)
    total_raw_rows = int(audit_all['Строк в файле'].sum()) if not audit_all.empty else len(df_full)
    duplicates_removed = total_raw_rows - len(df_full)

    # --- 2.1 ПАНЕЛЬ АУДИТА СКЛЕЙКИ ФАЙЛОВ И ЭКСПОРТ МАСТЕР-АРХИВА ---
    with st.expander(
        f"🗄️ Компилятор базы данных (Загружено файлов: {len(audit_all)} | Уникальных позиций: {len(df_full)} | Схлопнуто дублей из старых выгрузок: {duplicates_removed})",
        expanded=False
    ):
        ac1, ac2 = st.columns([7, 3])
        with ac1:
            st.caption("Система автоматически определяет возраст каждого файла по дате последнего заказа. Пересекающиеся заказы обновляются данными из самого свежего файла, а старые заказы (выпавшие из 3-месячного окна Ozon) бережно сохраняются.")
            st.dataframe(audit_all, hide_index=True, use_container_width=True)
        with ac2:
            st.markdown("**💾 Вечный Мастер-Архив**")
            st.caption("Скачайте объединенную базу всех загруженных файлов. В следующий раз вы сможете загрузить этот мастер-файл + только 1 свежую выгрузку Ozon.")
            export_cols = [c for c in df_full.columns if not c.startswith('_') and not c.endswith('_dt')]
            csv_master = df_full[export_cols].to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button(
                "📥 Скачать Мастер-Архив (.csv)",
                data=csv_master,
                file_name=f"dwina_master_archive_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

    # --- 2.2 ПАНЕЛЬ ГЛОБАЛЬНОЙ ФИЛЬТРАЦИИ ---
    with st.expander("🎛️ Глобальные фильтры среза (Период, Логистика, Товары, Бустинг)", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        min_d = df_full['Дата'].min().date()
        max_d = df_full['Дата'].max().date()
        
        date_range = fc1.date_input("Период заказов", value=(min_d, max_d), min_value=min_d, max_value=max_d)
        log_options = sorted(df_full['Логистика'].dropna().unique().tolist())
        sel_log = fc2.multiselect("Логистика", options=log_options, default=log_options)
        
        sku_col = 'Артикул' if 'Артикул' in df_full.columns else 'Тип_Чехла'
        sku_options = sorted(df_full[sku_col].dropna().astype(str).unique().tolist())
        sel_skus = fc3.multiselect("Артикул / Товар", options=sku_options, default=sku_options)
        
        promo_options = sorted(df_full['Тип_Продвижения'].dropna().unique().tolist())
        sel_promos = fc4.multiselect("Тип продвижения", options=promo_options, default=promo_options)

    # Применяем глобальные фильтры
    mask_global = (
        df_full['Логистика'].isin(sel_log) &
        df_full[sku_col].astype(str).isin(sel_skus) &
        df_full['Тип_Продвижения'].isin(sel_promos)
    )
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_d, end_d = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        mask_global = mask_global & (df_full['Дата'] >= start_d) & (df_full['Дата'] <= end_d)
        
    df_filtered_full = df_full[mask_global].copy()

    # Переключатель учета отмен (по умолчанию выключен — считаем все факты продаж)
    top_t1, top_t2 = st.columns([4, 6])
    exclude_cancels = top_t1.toggle(
        "📉 Вычитать отмененные заказы из общей статистики",
        value=False,
        help="Если выключено, графики и прогнозы показывают все факты спроса. Если включено — только выкупленные и доставляющиеся заказы."
    )
    
    if exclude_cancels and 'Статус' in df_filtered_full.columns:
        df = df_filtered_full[df_filtered_full['Статус'] != 'Отменён'].copy()
    else:
        df = df_filtered_full.copy()

    if df.empty:
        st.warning("По выбранным фильтрам нет заказов. Расширьте параметры фильтрации.")
        st.stop()

    # --- 2.5 СИНХРОНИЗИРОВАННЫЕ РАСЧЕТЫ И ШАПКА ОПЕРАТИВНОЙ СВОДКИ ---
    total_cancelled_rev = df_filtered_full[df_filtered_full.get('Статус') == 'Отменён']['Выручка'].sum() if 'Статус' in df_filtered_full.columns else 0
    total_cancelled_orders = df_filtered_full[df_filtered_full.get('Статус') == 'Отменён']['Номер заказа'].nunique() if 'Статус' in df_filtered_full.columns else 0
    
    in_transit_mask = df_filtered_full.get('Статус', pd.Series()).isin(['Доставляется', 'Ожидает в ПВЗ', 'Ожидает сборки', 'Ожидает отгрузки'])
    pipeline_rev = df_filtered_full[in_transit_mask]['Выручка'].sum()
    pipeline_items = df_filtered_full[in_transit_mask]['Штуки'].sum()

    total_rev = df['Выручка'].sum()
    total_items = df['Штуки'].sum()
    total_orders = df['Номер заказа'].nunique()
    total_clients = df['Client_ID'].nunique()

    max_date_full = df['Time_Full'].max()
    curr_month_str = max_date_full.strftime('%Y-%m')
    last_update_str = max_date_full.strftime('%d.%m.%Y в %H:%M')

    unique_months = sorted(df['Месяц'].unique())
    curr_month_df = df[df['Месяц'] == curr_month_str]
    curr_rev = curr_month_df['Выручка'].sum()
    curr_items = curr_month_df['Штуки'].sum()
    prev_rev = df[df['Месяц'] == unique_months[-2]]['Выручка'].sum() if len(unique_months) > 1 else 0

    last_7_days = max_date_full.normalize() - pd.Timedelta(days=7)
    recent_7d_df = df[df['Time_Full'] >= last_7_days]
    run_rate_rev = recent_7d_df['Выручка'].sum() / 7 if not recent_7d_df.empty else 0
    run_rate_items = recent_7d_df['Штуки'].sum() / 7 if not recent_7d_df.empty else 0
    
    days_in_month = calendar.monthrange(max_date_full.year, max_date_full.month)[1]
    elapsed_days = max_date_full.day
    remaining_days = days_in_month - elapsed_days
    forecast_rev = curr_rev + (run_rate_rev * remaining_days)
    forecast_items = curr_items + (run_rate_items * remaining_days)
    plan_completion = (curr_rev / forecast_rev * 100) if forecast_rev > 0 else 0

    short_stats = (
        f"📊 DWINA | Сводка\n"
        f"Всего: {fmt_money(total_rev)} ({fmt_num(total_items)} шт.)\n"
        f"За {curr_month_str}: {fmt_money(curr_rev)} ({fmt_num(curr_items)} шт.)\n"
        f"План до конца месяца: ~{fmt_money(forecast_rev)}\n"
        f"В пути (Пайплайн): {fmt_money(pipeline_rev)} ({fmt_num(pipeline_items)} шт.)\n"
        f"Прошлый месяц: {fmt_money(prev_rev)}\n"
        f"Актуально на: {last_update_str}"
    )

    full_stats = (
        f"🐺 DWINA | Полная аналитика\n"
        f"Актуально на: {last_update_str}\n\n"
        f"📦 ГЛОБАЛЬНО:\n"
        f"• Выручка: {fmt_money(total_rev)}\n"
        f"• Продано: {fmt_num(total_items)} шт. ({fmt_num(total_orders)} заказов)\n"
        f"• В пути (скоро на баланс): {fmt_money(pipeline_rev)} ({fmt_num(pipeline_items)} шт.)\n"
        f"• Отменено: {fmt_money(total_cancelled_rev)} ({fmt_num(total_cancelled_orders)} зак.)\n\n"
        f"🎯 ТЕКУЩИЙ МЕСЯЦ ({curr_month_str}):\n"
        f"• Факт: {fmt_money(curr_rev)} ({fmt_num(curr_items)} шт.)\n"
        f"• Прогноз: ~{fmt_money(forecast_rev)} (~{fmt_num(forecast_items)} шт.)\n\n"
        f"🕒 ПРОШЛЫЙ МЕСЯЦ:\n"
        f"• Факт: {fmt_money(prev_rev)}\n\n"
        f"🌐 dwina.ru"
    )

    head_c1, head_c2 = st.columns([8.5, 1.5], vertical_alignment="center")
    with head_c1:
        st.markdown(
            f"<span style='font-size: 1.02rem; color: #374151;'>"
            f"🟢 <b>Актуально на:</b> {last_update_str} &nbsp;|&nbsp; "
            f"🔥 <b>Факт месяца:</b> {fmt_money(curr_rev)} &nbsp;|&nbsp; "
            f"🎯 <b>План месяца:</b> <span style='color: #10B981; font-weight:700;'>~{fmt_money(forecast_rev)} ({plan_completion:.1f}%)</span> &nbsp;|&nbsp; "
            f"🚚 <b>В пути:</b> {fmt_money(pipeline_rev)} &nbsp;|&nbsp; "
            f"🕒 <b>Прошлый мес:</b> {fmt_money(prev_rev)}"
            f"</span>", 
            unsafe_allow_html=True
        )
    with head_c2:
        with st.popover("📋 Копировать", use_container_width=True):
            st.caption("Краткая сводка:")
            st.code(short_stats, language="markdown")
            st.caption("Полный отчет:")
            st.code(full_stats, language="markdown")
            
    st.markdown("<hr style='margin: 0.8rem 0 1.2rem 0;'>", unsafe_allow_html=True)

    # --- 3. ГЛОБАЛЬНЫЕ KPI КАРТОЧКИ ---
    avg_order_val = total_rev / total_orders if total_orders else 0
    avg_unit_price = total_rev / total_items if total_items else 0
    fbo_share_pct = (df[df['Логистика'] == 'FBO']['Выручка'].sum() / total_rev * 100) if total_rev > 0 else 0
    
    st.markdown(f"""
        <div style="display: flex; gap: 14px; flex-wrap: wrap;">
            <div class="kpi-card" style="flex: 1; min-width: 155px;">
                <div class="kpi-title">Общая выручка</div>
                <div class="kpi-value">{fmt_money(total_rev)}</div>
                <div class="kpi-sub">FBO: {fbo_share_pct:.1f}% | FBS: {100-fbo_share_pct:.1f}%</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 145px; border-left-color: #005BFF;">
                <div class="kpi-title">Всего заказов</div>
                <div class="kpi-value">{fmt_num(total_orders)}</div>
                <div class="kpi-sub">Уник. клиентов: {fmt_num(total_clients)}</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 145px; border-left-color: #10B981;">
                <div class="kpi-title">Продано штук</div>
                <div class="kpi-value">{fmt_num(total_items)}</div>
                <div class="kpi-sub">В среднем {total_items/total_orders if total_orders else 0:.2f} шт/заказ</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 145px; border-left-color: #8B5CF6;">
                <div class="kpi-title">Средний чек</div>
                <div class="kpi-value">{fmt_money(avg_order_val)}</div>
                <div class="kpi-sub">Средняя цена 1 шт: {fmt_money(avg_unit_price)}</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 155px; border-left-color: #F59E0B;">
                <div class="kpi-title">Деньги в пути</div>
                <div class="kpi-value">{fmt_money(pipeline_rev)}</div>
                <div class="kpi-sub">Едет к клиентам: {fmt_num(pipeline_items)} шт.</div>
            </div>
            <div class="kpi-card" style="flex: 1; min-width: 145px; border-left-color: #EF4444;">
                <div class="kpi-title">Отмены (Упущено)</div>
                <div class="kpi-value">{fmt_money(total_cancelled_rev)}</div>
                <div class="kpi-sub">Отменено заказов: {fmt_num(total_cancelled_orders)}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # --- НАВИГАЦИЯ ПО МОДУЛЯМ СИСТЕМЫ ---
    tab_main, tab_viral, tab_products, tab_clients, tab_logistics, tab_explorer = st.tabs([
        "📊 Главный Дашборд & Прогноз",
        "🏘️ Домовые Чаты & Всплески (Growth Hack)",
        "📦 Товары, Цены & Дефицит Склада",
        "🤝 Клиенты, LTV & Семейные Корзины",
        "🚚 Логистика, Сроки & Тарификация",
        "🗂️ Все Заказы (Поиск и Фильтры)"
    ])

    # =========================================================================
    # ВКЛАДКА 1: ГЛАВНЫЙ ДАШБОРД И ТАБЛИЦА ЖИЗНИ БИЗНЕСА
    # =========================================================================
    with tab_main:
        st.markdown("### 🎯 Выручка по месяцам")
        monthly_data = []
        for i, m_str in enumerate(unique_months):
            m_df = df[df['Месяц'] == m_str]
            m_num = int(m_str.split('-')[1])
            m_year = int(m_str.split('-')[0])
            m_name = f"{ru_months_nom[m_num]} {m_year}" if len(unique_months) > 12 else ru_months_nom[m_num]
            
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
                    p_fbs_rev = df_prev_same[df_prev_same['Логистика'] == 'FBS']['Выручка'].sum()
                    p_fbo_rev = df_prev_same[df_prev_same['Логистика'] == 'FBO']['Выручка'].sum()
                else:
                    p_rev = p_items = p_fbs_rev = p_fbo_rev = 0
                
                multiplier = days_in_month / elapsed_days if elapsed_days > 0 else 1
                proj_rev_m = m_rev * multiplier
                proj_items_m = m_items * multiplier
                
                hover_text = (
                    f"<b style='font-size: 14px;'>{m_name.upper()} (Аналитика за первые {elapsed_days} дн.)</b><br><br>"
                    f"Всего сейчас: <b>{m_rev:,.0f} ₽</b> {format_diff(m_rev, p_rev, True)} к {prev_name_dat}<br>"
                    f"Всего сейчас: <b>{m_items:.0f} шт.</b> {format_diff(m_items, p_items, False)} к {prev_name_dat}<br><br>"
                    f"FBS сейчас: {m_fbs_items:.0f} шт., <b>{m_fbs_rev:,.0f} ₽</b> {format_diff(m_fbs_rev, p_fbs_rev, True)}<br>"
                    f"FBO сейчас: {m_fbo_items:.0f} шт., <b>{m_fbo_rev:,.0f} ₽</b> {format_diff(m_fbo_rev, p_fbo_rev, True)}<br><br>"
                    f"<b>ПРОГНОЗ за ВЕСЬ {m_name.upper()} (прошло {elapsed_days} дн., осталось {days_in_month - elapsed_days}):</b><br>"
                    f"Линейная проекция: ~{proj_rev_m:,.0f} ₽ | ~{proj_items_m:.0f} шт.<br>"
                    f"По темпу последних 7 дн.: ~{forecast_rev:,.0f} ₽ | ~{forecast_items:.0f} шт."
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
                    f"FBS: {m_fbs_items:.0f} шт., <b>{m_fbs_rev:,.0f} ₽</b> {format_diff(m_fbs_rev, p_fbs_rev, True)}<br>"
                    f"FBO: {m_fbo_items:.0f} шт., <b>{m_fbo_rev:,.0f} ₽</b> {format_diff(m_fbo_rev, p_fbo_rev, True)}"
                )
                
            monthly_data.append({'Месяц': m_name, 'FBS_Выручка': m_fbs_rev, 'FBO_Выручка': m_fbo_rev, 'Hover': hover_text})
            
        df_monthly_viz = pd.DataFrame(monthly_data)
        fig_monthly = go.Figure()
        fig_monthly.add_trace(go.Bar(x=df_monthly_viz['Месяц'], y=df_monthly_viz['FBS_Выручка'], name='FBS (Свой склад)', marker_color='#FF5C00', customdata=df_monthly_viz['Hover'], hovertemplate="%{customdata}<extra></extra>"))
        fig_monthly.add_trace(go.Bar(x=df_monthly_viz['Месяц'], y=df_monthly_viz['FBO_Выручка'], name='FBO (Склады Ozon)', marker_color='#005BFF', customdata=df_monthly_viz['Hover'], hovertemplate="%{customdata}<extra></extra>"))
        fig_monthly.update_layout(
            barmode='stack', hovermode='closest', dragmode=False,
            hoverlabel=dict(bgcolor="white", font_size=13, bordercolor="#E5E7EB"),
            plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'),
            margin=dict(t=10, b=0, l=0, r=0), height=420,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        fig_monthly.update_xaxes(fixedrange=True)
        fig_monthly.update_yaxes(showgrid=True, gridcolor='#E5E7EB', title="Выручка (₽)", fixedrange=True)
        st.plotly_chart(fig_monthly, use_container_width=True, config=PLOT_CONFIG)

        st.markdown("<hr>", unsafe_allow_html=True)

        # --- ДИНАМИКА ПО ДНЯМ И ОРГАНИЧЕСКИЙ ТРЕНД ---
        st.markdown("### 📈 Динамика продаж по дням")
        min_date, max_date_f = df['Дата'].min(), df['Дата'].max()
        all_dates = pd.date_range(min_date, max_date_f)
        
        fbs_daily = df[df['Логистика'] == "FBS"].groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        fbo_daily = df[df['Логистика'] == "FBO"].groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        total_daily = df.groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        cancelled_daily = df_filtered_full[df_filtered_full.get('Статус') == 'Отменён'].groupby('Дата')['Выручка'].sum().reindex(all_dates, fill_value=0)
        
        fig_sales = go.Figure()
        fig_sales.add_trace(go.Scatter(x=all_dates, y=fbs_daily, name='FBS (Факт)', mode='lines', line=dict(color='#FF5C00', width=2)))
        fig_sales.add_trace(go.Scatter(x=all_dates, y=fbo_daily, name='FBO (Факт)', mode='lines', line=dict(color='#005BFF', width=2)))
        fig_sales.add_trace(go.Scatter(x=all_dates, y=total_daily, name='СУММА', mode='lines', line=dict(color='#10B981', width=3, dash='dot')))
        fig_sales.add_trace(go.Scatter(x=all_dates, y=cancelled_daily, name='Отмены (₽)', mode='lines', line=dict(color='#9CA3AF', width=1.5)))
        
        fig_sales.update_layout(hovermode="x unified", dragmode=False, plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'), margin=dict(t=10, b=10, l=0, r=0), height=380)
        fig_sales.update_xaxes(type='date', showgrid=True, gridcolor='#E5E7EB', tickformat="%d %b", fixedrange=True)
        fig_sales.update_yaxes(showgrid=True, gridcolor='#E5E7EB', title="Реальная выручка (₽)", fixedrange=True)
        st.plotly_chart(fig_sales, use_container_width=True, config=PLOT_CONFIG)
        
        st.markdown("#### 🌊 Органический тренд SMA-7 (Очищено от оптовых аномалий)")
        st.caption("Случайные оптовые закупки (по 3–6 шт. в одни руки) сведены к 1 средневзвешенному чеку. Показывает чистую скользящую среднюю (SMA-7) органического трафика.")
        daily_visits = df.groupby(['Дата', 'Client_ID']).agg({'Выручка': 'sum', 'Штуки': 'sum'}).reset_index()
        daily_visits['Цена_1_шт'] = np.where(daily_visits['Штуки'] > 0, daily_visits['Выручка'] / daily_visits['Штуки'], 0)
        total_organic_daily = daily_visits.groupby('Дата')['Цена_1_шт'].sum().reindex(all_dates, fill_value=0)
        trend_7d = total_organic_daily.rolling(window=7, min_periods=1).mean()
        
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=all_dates, y=trend_7d, name='SMA-7 (Органический тренд)', mode='lines', fill='tozeroy', line=dict(color='#8B5CF6', width=3), fillcolor='rgba(139, 92, 246, 0.18)'))
        fig_trend.update_layout(hovermode="x unified", dragmode=False, plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'), margin=dict(t=10, b=10, l=0, r=0), height=280)
        fig_trend.update_xaxes(type='date', showgrid=True, gridcolor='#E5E7EB', tickformat="%d %b", fixedrange=True)
        fig_trend.update_yaxes(showgrid=True, gridcolor='#E5E7EB', title="Усредненная выручка (₽)", fixedrange=True)
        st.plotly_chart(fig_trend, use_container_width=True, config=PLOT_CONFIG)

        st.markdown("<hr>", unsafe_allow_html=True)

        # --- ПРАЙМ-ТАЙМ И ТЕПЛОВАЯ МАТРИЦА ---
        st.markdown("### 🔥 Прайм-тайм, Дни недели и Тепловая карта покупательской активности")
        col_aud1, col_aud2 = st.columns(2)
        with col_aud1:
            def categorize_time(h):
                if 6 <= h < 12: return 'Утро (06-12)'
                elif 12 <= h < 18: return 'День (12-18)'
                elif 18 <= h < 24: return 'Вечер (18-24)'
                else: return 'Ночь (00-06)'

            df['Время_Суток'] = df['Час'].apply(categorize_time)
            tod_stats = df.groupby('Время_Суток')['Client_ID'].nunique().reset_index()
            fig_pie = px.pie(tod_stats, values='Client_ID', names='Время_Суток', hole=0.5, title="Визиты по времени суток", color_discrete_sequence=px.colors.sequential.Teal)
            fig_pie.update_layout(plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'), dragmode=False, height=340)
            st.plotly_chart(fig_pie, use_container_width=True, config=PLOT_CONFIG)
            
        with col_aud2:
            dow_map = {'Monday': 'ПН', 'Tuesday': 'ВТ', 'Wednesday': 'СР', 'Thursday': 'ЧТ', 'Friday': 'ПТ', 'Saturday': 'СБ', 'Sunday': 'ВС'}
            df['Day_RU'] = df['День_Недели'].map(dow_map)
            dow_order = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']
            dow_stats = df.groupby('Day_RU')['Client_ID'].nunique().reindex(dow_order).fillna(0).reset_index()
            
            total_visits = dow_stats['Client_ID'].sum()
            dow_stats['Percent'] = np.where(total_visits > 0, (dow_stats['Client_ID'] / total_visits) * 100, 0)
            
            fig_dow = px.bar(dow_stats, x='Day_RU', y='Percent', title="Распределение покупателей по дням недели (%)", text=dow_stats['Percent'].apply(lambda x: f"{x:.1f}%"))
            fig_dow.update_layout(plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'), dragmode=False, height=340)
            fig_dow.update_traces(marker_color='#10B981', textposition='outside')
            fig_dow.update_xaxes(fixedrange=True)
            fig_dow.update_yaxes(title="Доля визитов (%)", showgrid=True, gridcolor='#E5E7EB', fixedrange=True, range=[0, dow_stats['Percent'].max() * 1.2 + 5])
            st.plotly_chart(fig_dow, use_container_width=True, config=PLOT_CONFIG)

        st.markdown("<hr>", unsafe_allow_html=True)

        # --- ГЛОБАЛЬНАЯ ТАБЛИЦА ЖИЗНИ БИЗНЕСА (АРХИВ + ТЕКУЩИЙ + AI ПРОГНОЗ) ---
        st.markdown("### 🧠 Таблица жизни — Архив & Умный AI-Прогноз на 12 месяцев")
        col_eco1, col_eco2, col_eco3 = st.columns(3)
        cogs = col_eco1.number_input("Себестоимость 1 шт. (₽)", value=4.0, step=0.5)
        ozon_fee = col_eco2.slider("Доля маркетплейса (%)", 10.0, 90.0, 75.0)
        decay_factor = col_eco3.slider("Коэффициент сохранения темпа (AI-ускорение)", 0.50, 1.05, 0.85, step=0.05, help="0.85 — плавное рыночное затухание; 1.00 — сохранение текущего темпа гиперроста без торможения.")
        
        monthly_summary = df.groupby('Месяц').agg({'Выручка': 'sum', 'Штуки': 'sum'}).reset_index()
        fbo_agg = df[df['Логистика'] == 'FBO'].groupby('Месяц')['Выручка'].sum().to_dict()
        fbs_agg = df[df['Логистика'] == 'FBS'].groupby('Месяц')['Выручка'].sum().to_dict()
        
        table_data = []
        for i, m_str in enumerate(unique_months):
            if m_str == curr_month_str: continue
            y, m = map(int, m_str.split('-'))
            m_name = f"{ru_months_nom[m]} {y}"
            rev = monthly_summary.loc[monthly_summary['Месяц'] == m_str, 'Выручка'].values[0]
            items = monthly_summary.loc[monthly_summary['Месяц'] == m_str, 'Штуки'].values[0]
            table_data.append({
                "Месяц": m_name, "Статус": "Архив (Факт)", "Выручка (₽)": rev,
                "Штук": items, "FBS (₽)": fbs_agg.get(m_str, 0), "FBO (₽)": fbo_agg.get(m_str, 0)
            })

        curr_rev_val = monthly_summary.loc[monthly_summary['Месяц'] == curr_month_str, 'Выручка'].values[0]
        curr_items_val = monthly_summary.loc[monthly_summary['Месяц'] == curr_month_str, 'Штуки'].values[0]
        multiplier_curr = days_in_month / elapsed_days if elapsed_days > 0 else 1
        
        proj_rev_curr = curr_rev_val * multiplier_curr
        proj_items_curr = curr_items_val * multiplier_curr
        fbo_ratio = fbo_agg.get(curr_month_str, 0) / curr_rev_val if curr_rev_val > 0 else 0.5
        fbs_ratio = 1 - fbo_ratio
        
        table_data.append({
            "Месяц": f"{ru_months_nom[max_date_full.month]} {max_date_full.year}",
            "Статус": "Текущий (Проекция)", "Выручка (₽)": proj_rev_curr,
            "Штук": proj_items_curr, "FBS (₽)": proj_rev_curr * fbs_ratio, "FBO (₽)": proj_rev_curr * fbo_ratio
        })

        hist_revs = monthly_summary.set_index('Месяц')['Выручка'].to_dict()
        hist_revs[curr_month_str] = proj_rev_curr
        m_keys = sorted(hist_revs.keys())
        growths = [hist_revs[m_keys[i]] / hist_revs[m_keys[i-1]] for i in range(1, len(m_keys)) if hist_revs[m_keys[i-1]] > 0]
        
        if len(growths) >= 2:
            ai_multiplier = growths[-1] * 0.7 + growths[-2] * 0.3
        elif len(growths) == 1:
            ai_multiplier = growths[0]
        else:
            ai_multiplier = 1.5
            
        run_rev = proj_rev_curr
        run_items = proj_items_curr
        curr_dt = max_date_full
        
        for i in range(1, 13):
            m_step = curr_dt.month - 1 + 1
            y_step = curr_dt.year + m_step // 12
            m_step = m_step % 12 + 1
            curr_dt = datetime(y_step, m_step, 1)
            
            ai_multiplier = 1.0 + ((ai_multiplier - 1.0) * decay_factor)
            run_rev *= ai_multiplier
            run_items *= ai_multiplier
            
            table_data.append({
                "Месяц": f"{ru_months_nom[m_step]} {y_step}",
                "Статус": "AI-Прогноз", "Выручка (₽)": run_rev,
                "Штук": run_items, "FBS (₽)": run_rev * fbs_ratio, "FBO (₽)": run_rev * fbo_ratio
            })

        df_table = pd.DataFrame(table_data)
        df_table['Чистая Прибыль (сырая)'] = df_table['Выручка (₽)'] - (df_table['Штук'] * cogs) - (df_table['Выручка (₽)'] * (ozon_fee / 100))
        df_table['Динамика'] = df_table['Чистая Прибыль (сырая)'].pct_change() * 100

        def format_profit(row):
            val = row['Чистая Прибыль (сырая)']
            diff = row['Динамика']
            val_str = fmt_money(val)
            if pd.isna(diff) or np.isinf(diff):
                return val_str
            sign = "+" if diff > 0 else ""
            return f"{val_str} ({sign}{diff:.1f}%)"
            
        df_table['Чистая Прибыль'] = df_table.apply(format_profit, axis=1)

        st.dataframe(
            df_table,
            column_config={
                "Месяц": st.column_config.TextColumn("Месяц"),
                "Статус": st.column_config.TextColumn("Статус"),
                "Выручка (₽)": st.column_config.NumberColumn("Выручка (₽)", format="%d ₽"),
                "Штук": st.column_config.NumberColumn("Спрос (Штук)", format="%d"),
                "FBS (₽)": st.column_config.NumberColumn("FBS", format="%d ₽"),
                "FBO (₽)": st.column_config.NumberColumn("FBO", format="%d ₽"),
                "Чистая Прибыль": st.column_config.TextColumn("Чистая Прибыль и динамика MoM")
            },
            column_order=["Месяц", "Статус", "Выручка (₽)", "Штук", "FBS (₽)", "FBO (₽)", "Чистая Прибыль"],
            hide_index=True, use_container_width=True, height=580
        )

    # =========================================================================
    # ВКЛАДКА 2: РАДАР ДОМОВЫХ ЧАТОВ И ВИРУСНЫХ ВСПЛЕСКОВ (GROWTH HACK)
    # =========================================================================
    with tab_viral:
        st.markdown("### 🏘️ Радар «Домовых чатов ЖК» и Вирусных Всплесков")
        st.markdown("""
        <div class="insight-box">
            <b>Как работает детектор сарафанного радио (Алгоритм «Нулевого пациента»):</b><br>
            1. Когда покупатель забирает заказ из ПВЗ, надевает чехол на ключ ЛСР, видит твой вкладыш и кидает фото со ссылкой в чат своего дома (ЖК) — в течение следующих нескольких часов происходит <b>кластерный всплеск заказов от РАЗНЫХ покупателей</b>.<br>
            2. Алгоритм ниже отсекает одиночных оптовиков (схлопывая заказы одного <code>Client_ID</code>) и ищет волны, где за короткое окно времени пришло сразу несколько разных соседей.<br>
            3. Для каждой волны радар сканирует колонку <code>Дата доставки</code> за <b>1–36 часов до начала всплеска</b> и находит <b>«Амбассадора ЖК»</b> — клиента, который только что забрал чехол в ПВЗ и запустил цепную реакцию!
        </div>
        """, unsafe_allow_html=True)

        vc1, vc2, vc3 = st.columns(3)
        window_hours = vc1.slider("Окно плотности волны (часов)", min_value=2, max_value=24, value=6, step=1)
        min_neighbors = vc2.slider("Минимум РАЗНЫХ покупателей в волне", min_value=2, max_value=8, value=3, step=1)
        lookback_delivery_h = vc3.slider("Окно поиска «Амбассадора» после ПВЗ (часов до волны)", min_value=6, max_value=72, value=36, step=6)

        # Группируем до уникальных визитов клиентов, чтобы 1 человек с 4 заказами подряд считался за 1 соседа
        orders_by_client = df.sort_values('Time_Full').groupby(['Номер заказа']).agg(
            Time_Full=('Time_Full', 'min'),
            Client_ID=('Client_ID', 'first'),
            Логистика=('Логистика', 'first'),
            Штуки=('Штуки', 'sum'),
            Выручка=('Выручка', 'sum'),
            Артикулы=('Тип_Чехла', lambda s: ', '.join(s.unique())),
            Статус=('Статус', 'first')
        ).reset_index().sort_values('Time_Full').reset_index(drop=True)

        # Вычисляем скользящую плотность уникальных клиентов
        times_list = orders_by_client['Time_Full'].tolist()
        clients_list = orders_by_client['Client_ID'].tolist()
        
        density_counts = []
        burst_clusters = []
        visited_indices = set()

        for idx_t, t_curr in enumerate(times_list):
            t_end = t_curr + pd.Timedelta(hours=window_hours)
            in_win_idx = [j for j, t_j in enumerate(times_list) if t_curr <= t_j <= t_end]
            uniq_c = list(dict.fromkeys(clients_list[j] for j in in_win_idx))
            density_counts.append(len(uniq_c))
            
            if len(uniq_c) >= min_neighbors and not any(i in visited_indices for i in in_win_idx):
                for i in in_win_idx:
                    visited_indices.add(i)
                sub_df = orders_by_client.iloc[in_win_idx]
                w_start = sub_df['Time_Full'].min()
                w_end = sub_df['Time_Full'].max()
                
                # Ищем Амбассадора (кто забрал заказ из ПВЗ за lookback_delivery_h часов до w_start)
                ambassador_str = "Не найден в окне доставки"
                if 'Дата доставки_dt' in df.columns:
                    deliv_candidates = df[
                        (df['Дата доставки_dt'] >= w_start - pd.Timedelta(hours=lookback_delivery_h)) &
                        (df['Дата доставки_dt'] <= w_start)
                    ].sort_values('Дата доставки_dt', ascending=False)
                    if not deliv_candidates.empty:
                        amb_list = []
                        for _, r_amb in deliv_candidates.drop_duplicates(subset=['Client_ID']).head(2).iterrows():
                            diff_h = (w_start - r_amb['Дата доставки_dt']).total_seconds() / 3600.0
                            amb_list.append(f"Клиент {r_amb['Client_ID']} (забрал в ПВЗ за {diff_h:.1f} ч. до волны, заказ {r_amb['Номер заказа']})")
                        ambassador_str = " / ".join(amb_list)

                burst_clusters.append({
                    'Начало волны': w_start.strftime('%d.%m.%Y %H:%M'),
                    'Конец волны': w_end.strftime('%d.%m.%Y %H:%M'),
                    'Длительность': f"{(w_end - w_start).total_seconds()/3600:.1f} ч.",
                    'Уникальных соседей (Client_ID)': len(uniq_c),
                    'Куплено (шт.)': int(sub_df['Штуки'].sum()),
                    'Выручка волны (₽)': sub_df['Выручка'].sum(),
                    'Каналы': ', '.join(sub_df['Логистика'].unique()),
                    'Вероятный Амбассадор (Забрал из ПВЗ накануне)': ambassador_str,
                    'Заказы в волне': ', '.join(sub_df['Номер заказа'].tolist())
                })

        orders_by_client['Соседей_в_окне'] = density_counts

        # График импульсов домовых чатов
        fig_burst = go.Figure()
        fig_burst.add_trace(go.Scatter(
            x=orders_by_client['Time_Full'], y=orders_by_client['Соседей_в_окне'],
            mode='lines+markers', name='Уникальных покупателей в окне',
            line=dict(color='#005BFF', width=2),
            marker=dict(
                size=np.where(orders_by_client['Соседей_в_окне'] >= min_neighbors, 10, 5),
                color=np.where(orders_by_client['Соседей_в_окне'] >= min_neighbors, '#EF4444', '#005BFF')
            ),
            customdata=orders_by_client['Номер заказа'] + " | " + orders_by_client['Артикулы'],
            hovertemplate="<b>%{x|%d.%m.%Y %H:%M}</b><br>Уникальных покупателей за окно: <b>%{y}</b><br>%{customdata}<extra></extra>"
        ))
        fig_burst.add_hline(y=min_neighbors, line_dash="dash", line_color="#EF4444", annotation_text=f"Порог всплеска чата ЖК ({min_neighbors}+ соседа)")
        fig_burst.update_layout(
            title=f"Кардиограмма вирусных импульсов (число разных покупателей за {window_hours} ч.)",
            plot_bgcolor='white', paper_bgcolor='white', font=dict(color='#111827'),
            dragmode=False, height=340, margin=dict(t=40, b=10, l=0, r=0)
        )
        fig_burst.update_xaxes(fixedrange=True, showgrid=True, gridcolor='#E5E7EB')
        fig_burst.update_yaxes(fixedrange=True, showgrid=True, gridcolor='#E5E7EB', title="Уникальных покупателей")
        st.plotly_chart(fig_burst, use_container_width=True, config=PLOT_CONFIG)

        if burst_clusters:
            st.success(f"🔥 Обнаружено **{len(burst_clusters)}** выраженных вирусных волн! Ниже показаны сами волны и клиенты, которые забрали посылку из ПВЗ прямо перед всплеском.")
            df_bursts = pd.DataFrame(burst_clusters).sort_values('Выручка волны (₽)', ascending=False)
            st.dataframe(
                df_bursts,
                column_config={
                    "Выручка волны (₽)": st.column_config.NumberColumn("Выручка волны", format="%d ₽"),
                    "Уникальных соседей (Client_ID)": st.column_config.NumberColumn("Соседей в волне", format="%d чел."),
                },
                hide_index=True, use_container_width=True
            )
        else:
            st.info("При текущих настройках ползунков взрывных волн не найдено. Увеличьте окно часов или уменьшите порог соседей.")

        # Проверка наличия гео-колонок Ozon
        geo_cols = [c for c in df.columns if any(k in c.lower() for k in ['кластер', 'город', 'регион'])]
        if geo_cols:
            st.markdown("#### 🗺️ География и Кластеры доставки")
            g_col = geo_cols[0]
            geo_stats = df.groupby(g_col).agg(
                Заказов=('Номер заказа', 'nunique'),
                Клиентов=('Client_ID', 'nunique'),
                Штук=('Штуки', 'sum'),
                Выручка=('Выручка', 'sum')
            ).reset_index().sort_values('Выручка', ascending=False)
            st.dataframe(geo_stats, hide_index=True, use_container_width=True)
        else:
            st.caption("💡 **Совет Маркетинг-директора:** Чтобы видеть конкретный город и ЖК каждого всплеска, при скачивании CSV в Ozon Seller разверните блок *«Настройки отчета / Столбцы»* и поставьте галочки **«Кластер доставки»** и **«Город доставки»**. Как только эти колонки появятся в файле, здесь автоматически построится карта ЖК по городам!")

    # =========================================================================
    # ВКЛАДКА 3: ТОВАРЫ, ЦЕНОВАЯ ЭЛАСТИЧНОСТЬ, БУСТИНГ И ДЕФИЦИТ СКЛАДА
    # =========================================================================
    with tab_products:
        st.markdown("### 📦 Товарная матрица (Объединение по Артикулу / SKU)")
        group_col = 'Артикул' if 'Артикул' in df.columns else ('SKU' if 'SKU' in df.columns else 'Тип_Чехла')
        
        prod_stats = df.groupby(group_col).agg(
            Выручка=('Выручка', 'sum'),
            Штук=('Штуки', 'sum'),
            Заказов=('Номер заказа', 'nunique'),
            Оплачено_Покупателем=('Оплачено_покупателем', lambda s: (s * df.loc[s.index, 'Штуки']).sum()),
            Название=('Название товара', lambda x: x.mode()[0] if not x.empty and 'Название товара' in df.columns else 'Неизвестно'),
            Цвет=('Цвет товара', lambda x: x.dropna().mode()[0] if not x.dropna().empty else 'Базовый / Сюрприз')
        ).reset_index().sort_values('Выручка', ascending=False)
        
        prod_stats['Модель / Цвет'] = prod_stats['Название'].apply(lambda x: str(x).split('для')[0].strip() if pd.notna(x) else 'Неизвестно')
        prod_stats['Ср_Цена_Селлера'] = (prod_stats['Выручка'] / prod_stats['Штук'].replace(0, 1)).round(0)
        prod_stats['Ср_Цена_Покупателя'] = (prod_stats['Оплачено_Покупателем'] / prod_stats['Штук'].replace(0, 1)).round(0)
        prod_stats['Доля_%'] = (prod_stats['Выручка'] / total_rev * 100).round(1)
        
        st.dataframe(
            prod_stats[[group_col, 'Модель / Цвет', 'Цвет', 'Выручка', 'Штук', 'Ср_Цена_Селлера', 'Ср_Цена_Покупателя', 'Доля_%']],
            column_config={
                group_col: st.column_config.TextColumn("Артикул", width="medium"),
                "Модель / Цвет": st.column_config.TextColumn("Витринное название", width="medium"),
                "Цвет": st.column_config.TextColumn("Цвет Ozon", width="small"),
                "Выручка": st.column_config.ProgressColumn("Выручка Селлера (₽)", format="%d ₽", min_value=0, max_value=int(prod_stats['Выручка'].max())),
                "Штук": st.column_config.NumberColumn("Продано (шт)", format="%d шт."),
                "Ср_Цена_Селлера": st.column_config.NumberColumn("Твоя цена (1 шт)", format="%d ₽"),
                "Ср_Цена_Покупателя": st.column_config.NumberColumn("Цена для клиента (с СПП)", format="%d ₽"),
                "Доля_%": st.column_config.NumberColumn("Доля выручки", format="%.1f %%")
            },
            hide_index=True, use_container_width=True
        )

        st.markdown("<hr>", unsafe_allow_html=True)

        # --- ПЛАН ПРОИЗВОДСТВА И ДЕФИЦИТ СКЛАДОВ ---
        st.markdown("#### 🏭 План производства и Дефицит складов (На 30 дней)")
        st.caption("Прогноз спроса рассчитывается с учетом как общей скорости продаж, так и ускорения за последние 14 дней.")

        days_in_data = max((df['Дата'].max() - df['Дата'].min()).days + 1, 1)
        recent_14d_cutoff = df['Дата'].max() - pd.Timedelta(days=14)
        recent_14d_sku = df[df['Дата'] > recent_14d_cutoff].groupby(group_col)['Штуки'].sum().to_dict()

        if 'stock_values' not in st.session_state:
            st.session_state.stock_values = {}

        deficit_df = prod_stats[[group_col, 'Модель / Цвет', 'Штук']].copy()
        # Умный спрос: берем максимум между историческим средним и темпом последних 14 дней
        deficit_df['Темп_14дн_в_мес'] = deficit_df[group_col].map(lambda k: np.ceil(recent_14d_sku.get(k, 0) / 14.0 * 30.0)).astype(int)
        deficit_df['Прогноз (30 дн)'] = np.maximum(
            np.ceil((deficit_df['Штук'] / days_in_data) * 30).astype(int),
            deficit_df['Темп_14дн_в_мес']
        )
        deficit_df['Сейчас на складе ✍️'] = (
            deficit_df['Модель / Цвет'].map(st.session_state.stock_values).fillna(0).astype(int)
        )
        deficit_df['Дефицит'] = deficit_df['Прогноз (30 дн)'] - deficit_df['Сейчас на складе ✍️']
        deficit_df['Статус Производства'] = deficit_df['Дефицит'].apply(
            lambda x: f"🛑 Напечатать {int(x)} шт." if x > 0 else "✅ Хватает"
        )

        edited_deficit = st.data_editor(
            deficit_df[['Модель / Цвет', 'Прогноз (30 дн)', 'Сейчас на складе ✍️', 'Дефицит', 'Статус Производства']],
            column_config={
                "Модель / Цвет": st.column_config.TextColumn("Товар", disabled=True, width="medium"),
                "Прогноз (30 дн)": st.column_config.NumberColumn("Спрос на 30 дней", disabled=True, format="%d шт."),
                "Сейчас на складе ✍️": st.column_config.NumberColumn("Сейчас на складе ✍️", min_value=0, step=1, format="%d шт."),
                "Дефицит": st.column_config.NumberColumn("Дефицит", disabled=True, format="%d шт."),
                "Статус Производства": st.column_config.TextColumn("Статус производства", disabled=True, width="medium"),
            },
            hide_index=True, use_container_width=True, key="stock_editor"
        )

        new_stocks = dict(zip(edited_deficit['Модель / Цвет'], edited_deficit['Сейчас на складе ✍️']))
        if new_stocks != st.session_state.stock_values:
            st.session_state.stock_values = new_stocks
            st.rerun()

        st.markdown("<hr>", unsafe_allow_html=True)

        # --- ЭКОНОМИКА БУСТИНГА, АКЦИЙ И ЦЕНОВЫХ КОРИДОРОВ OZON ---
        st.markdown("### 🚀 Эффективность Бустинга, СПП (Соинвест Ozon) и Ценовые Коридоры")
        pc1, pc2 = st.columns(2)
        with pc1:
            promo_stats = df.groupby('Тип_Продвижения').agg(
                Заказов=('Номер заказа', 'nunique'),
                Штук=('Штуки', 'sum'),
                Выручка=('Выручка', 'sum'),
                Ср_Чек=('Цена_1_шт', 'mean')
            ).reset_index().sort_values('Выручка', ascending=False)
            fig_promo = px.bar(
                promo_stats, x='Тип_Продвижения', y='Выручка', color='Тип_Продвижения',
                title="Выручка в разрезе инструментов продвижения Ozon",
                text=promo_stats['Штук'].apply(lambda x: f"{x:.0f} шт.")
            )
            fig_promo.update_layout(plot_bgcolor='white', paper_bgcolor='white', showlegend=False, dragmode=False, height=350)
            fig_promo.update_xaxes(fixedrange=True, title="")
            fig_promo.update_yaxes(fixedrange=True, showgrid=True, gridcolor='#E5E7EB', title="Выручка (₽)")
            st.plotly_chart(fig_promo, use_container_width=True, config=PLOT_CONFIG)

        with pc2:
            def price_tier(p):
                if p < 90: return "1. Локомотив (< 90 ₽)"
                elif p < 140: return "2. Базовый (90–139 ₽)"
                elif p < 200: return "3. Средний+ (140–199 ₽)"
                elif p <= 299: return "4. Премиум до порога (200–299 ₽)"
                else: return "5. Свыше 300 ₽ (Высокий тариф)"

            df['Ценовой_Коридор'] = df['Цена_1_шт'].apply(price_tier)
            tier_stats = df.groupby('Ценовой_Коридор').agg(
                Штук=('Штуки', 'sum'),
                Выручка=('Выручка', 'sum')
            ).reset_index().sort_values('Ценовой_Коридор')
            fig_tier = px.bar(
                tier_stats, x='Ценовой_Коридор', y='Выручка',
                title="Эластичность по ценовым коридорам (Контроль порога 300 ₽)",
                text=tier_stats['Штук'].apply(lambda x: f"{x:.0f} шт.")
            )
            fig_tier.update_traces(marker_color='#8B5CF6')
            fig_tier.update_layout(plot_bgcolor='white', paper_bgcolor='white', dragmode=False, height=350)
            fig_tier.update_xaxes(fixedrange=True, title="")
            fig_tier.update_yaxes(fixedrange=True, showgrid=True, gridcolor='#E5E7EB', title="Выручка (₽)")
            st.plotly_chart(fig_tier, use_container_width=True, config=PLOT_CONFIG)

    # =========================================================================
    # ВКЛАДКА 4: КЛИЕНТЫ, LTV И СЕМЕЙНЫЕ КОРЗИНЫ
    # =========================================================================
    with tab_clients:
        st.markdown("### 🤝 База возвращающихся клиентов (LTV и Кросс-канальные покупки)")
        clients_df = df.groupby('Client_ID').agg(
            Дней_Покупок=('Дата', 'nunique'),
            Заказов=('Номер заказа', 'nunique'),
            Штук_Всего=('Штуки', 'sum'),
            Общая_Выручка=('Выручка', 'sum'),
            Каналы=('Логистика', lambda s: ', '.join(sorted(s.unique()))),
            Товары=('Тип_Чехла', lambda s: ', '.join(s.unique())),
            Первая_Покупка=('Дата', 'min'),
            Последняя_Покупка=('Дата', 'max'),
            Даты_Заказов=('Дата', lambda x: ", ".join(sorted([d.strftime('%d.%m.%Y') for d in x.unique()])))
        ).reset_index()
        
        clients_df['Интервал_возврата_дн'] = (clients_df['Последняя_Покупка'] - clients_df['Первая_Покупка']).dt.days
        ltv_clients = clients_df[clients_df['Дней_Покупок'] > 1].sort_values('Общая_Выручка', ascending=False)
        
        lc1, lc2, lc3 = st.columns(3)
        lc1.metric("Повторных клиентов (в разные дни)", f"{len(ltv_clients)} чел.", f"{len(ltv_clients)/len(clients_df)*100:.1f}% от базы")
        lc2.metric("Выручка от повторных клиентов", fmt_money(ltv_clients['Общая_Выручка'].sum()), f"{ltv_clients['Штук_Всего'].sum():.0f} шт.")
        lc3.metric("Средний цикл возврата за 2-й покупкой", f"{ltv_clients['Интервал_возврата_дн'].mean():.1f} дн." if not ltv_clients.empty else "0 дн.")

        st.dataframe(
            ltv_clients[['Client_ID', 'Дней_Покупок', 'Заказов', 'Штук_Всего', 'Общая_Выручка', 'Интервал_возврата_дн', 'Каналы', 'Даты_Заказов', 'Товары']],
            column_config={
                "Client_ID": st.column_config.TextColumn("ID Покупателя"),
                "Дней_Покупок": st.column_config.NumberColumn("Визитов (в разные дни)", format="%d"),
                "Заказов": st.column_config.NumberColumn("Всего заказов", format="%d"),
                "Штук_Всего": st.column_config.NumberColumn("Куплено (шт)", format="%d шт."),
                "Общая_Выручка": st.column_config.NumberColumn("LTV Выручка", format="%d ₽"),
                "Интервал_возврата_дн": st.column_config.NumberColumn("Жизненный цикл (дн.)", format="%d дн."),
                "Каналы": st.column_config.TextColumn("Логистика"),
                "Даты_Заказов": st.column_config.TextColumn("Даты визитов", width="medium"),
                "Товары": st.column_config.TextColumn("Купленные модели", width="large")
            },
            hide_index=True, use_container_width=True
        )

        st.markdown("<hr>", unsafe_allow_html=True)

        # --- АНАЛИЗ СЕМЕЙНЫХ КОРЗИН (ПО СКОЛЬКО ШТУК БЕРУТ ЗА РАЗ) ---
        st.markdown("### 👨‍👩‍👧‍👦 Структура «Семейных корзин» (Сколько штук берут в один день)")
        basket_df = df.groupby(['Дата', 'Client_ID']).agg(
            Штук_в_руки=('Штуки', 'sum'),
            Выручка_корзины=('Выручка', 'sum'),
            Разных_Артикулов=(group_col, 'nunique')
        ).reset_index()
        
        basket_df['Размер корзины'] = basket_df['Штук_в_руки'].apply(
            lambda x: "1 шт. (Одиночный)" if x == 1 else ("2 шт. (Пара)" if x == 2 else ("3 шт. (Семья)" if x == 3 else f"4+ шт. (Опт: до {int(basket_df['Штук_в_руки'].max())} шт.)"))
        )
        b_stats = basket_df.groupby('Размер корзины').agg(
            Покупателей=('Client_ID', 'count'),
            Штук_Всего=('Штук_в_руки', 'sum'),
            Выручка=('Выручка_корзины', 'sum')
        ).reset_index()
        
        bc1, bc2 = st.columns(2)
        with bc1:
            fig_b = px.pie(b_stats, values='Выручка', names='Размер корзины', hole=0.45, title="Доля выручки от одиночных и семейных покупок")
            fig_b.update_layout(plot_bgcolor='white', paper_bgcolor='white', dragmode=False, height=340)
            st.plotly_chart(fig_b, use_container_width=True, config=PLOT_CONFIG)
        with bc2:
            st.markdown("**Детализация по глубине чека:**")
            st.dataframe(
                b_stats,
                column_config={
                    "Выручка": st.column_config.NumberColumn("Выручка", format="%d ₽"),
                    "Штук_Всего": st.column_config.NumberColumn("Продано штук", format="%d шт.")
                },
                hide_index=True, use_container_width=True
            )
            multi_sku_baskets = len(basket_df[basket_df['Разных_Артикулов'] > 1])
            st.info(f"🎨 **Комбинированные корзины:** В **{multi_sku_baskets}** случаях покупатели собирали в один заказ сразу несколько РАЗНЫХ цветов/артикулов (отличный сигнал для запуска карточки «Семейный набор из 3 разных цветов»).")

    # =========================================================================
    # ВКЛАДКА 5: ЛОГИСТИКА, СРОКИ ДОСТАВКИ И ТАРИФИКАЦИЯ
    # =========================================================================
    with tab_logistics:
        st.markdown("### 🚚 Деньги в пути (Pipeline) и Скорость доставки FBO vs FBS")
        deliv_valid = df[df['Дней_в_пути'].notna() & (df['Дней_в_пути'] >= 0)]
        
        lg1, lg2, lg3, lg4 = st.columns(4)
        fbo_days = deliv_valid[deliv_valid['Логистика'] == 'FBO']['Дней_в_пути'].mean()
        fbs_days = deliv_valid[deliv_valid['Логистика'] == 'FBS']['Дней_в_пути'].mean()
        
        lg1.metric("Средняя скорость FBO", f"{fbo_days:.1f} дн." if pd.notna(fbo_days) else "Нет данных")
        lg2.metric("Средняя скорость FBS", f"{fbs_days:.1f} дн." if pd.notna(fbs_days) else "Нет данных")
        lg3.metric("Едет к клиентам (В пути)", fmt_money(pipeline_rev), f"{fmt_num(pipeline_items)} шт.")
        
        cancel_rate_pct = (total_cancelled_orders / df_filtered_full['Номер заказа'].nunique() * 100) if df_filtered_full['Номер заказа'].nunique() > 0 else 0
        lg4.metric("Процент отмен заказов", f"{cancel_rate_pct:.1f}%", f"{fmt_num(total_cancelled_orders)} зак.")

        col_l1, col_l2 = st.columns(2)
        with col_l1:
            st.markdown("#### 📦 Заказы в пути и Ожидающие в ПВЗ (Скоро на баланс)")
            df_in_transit = df_filtered_full[in_transit_mask].sort_values('Time_Full', ascending=False)
            if not df_in_transit.empty:
                st.dataframe(
                    df_in_transit[['Номер отправления', 'Принят в обработку', 'Логистика', 'Статус', 'Тип_Чехла', 'Штуки', 'Выручка']],
                    column_config={"Выручка": st.column_config.NumberColumn("Сумма", format="%d ₽")},
                    hide_index=True, use_container_width=True, height=320
                )
            else:
                st.success("Все отправленные заказы уже получены клиентами!")

        with col_l2:
            st.markdown("#### ⚡ Тарификация FBS и Дисциплина отгрузки")
            if 'Фактическая тарификация' in df.columns and df['Фактическая тарификация'].notna().any():
                tar_stats = df[df['Логистика'] == 'FBS'].groupby('Фактическая тарификация').agg(
                    Отправлений=('Номер отправления', 'nunique'),
                    Выручка=('Выручка', 'sum')
                ).reset_index()
                st.dataframe(tar_stats, hide_index=True, use_container_width=True)
                st.caption("«Скидка 2%» начисляется Ozon за быструю передачу отправлений в ПВЗ раньше дедлайна.")
            else:
                st.info("Данные о фактической тарификации FBS отсутствуют в текущей выборке.")

    # =========================================================================
    # ВКЛАДКА 6: ПОЛНЫЙ РЕЕСТР ВСЕХ ЗАКАЗОВ (CRM & ORDER EXPLORER)
    # =========================================================================
    with tab_explorer:
        st.markdown("### 🗂️ Полный реестр всех заказов и отправлений")
        ex1, ex2, ex3, ex4 = st.columns([3, 2.5, 2.5, 2])
        search_query = ex1.text_input("🔍 Поиск (Номер заказа, Client_ID, Артикул, Этикетка)", placeholder="Например: 47947448 или purple_vibe...")
        
        status_opts = sorted(df_filtered_full['Статус'].dropna().unique().tolist()) if 'Статус' in df_filtered_full.columns else []
        sel_statuses = ex2.multiselect("Статус заказа", options=status_opts, default=status_opts)
        
        basket_filter = ex3.selectbox("Фильтр по типу покупки", [
            "Все заказы",
            "Только оптовые / семейные (≥ 2 шт.)",
            "Только повторные клиенты (LTV)",
            "Только в пути / ПВЗ",
            "Только отмененные"
        ])
        min_sum_filter = ex4.number_input("Мин. сумма отправления (₽)", min_value=0, value=0, step=50)

        explorer_df = df_filtered_full.copy()
        if sel_statuses and 'Статус' in explorer_df.columns:
            explorer_df = explorer_df[explorer_df['Статус'].isin(sel_statuses)]
        if min_sum_filter > 0:
            explorer_df = explorer_df[explorer_df['Выручка'] >= min_sum_filter]
            
        if basket_filter == "Только оптовые / семейные (≥ 2 шт.)":
            explorer_df = explorer_df[explorer_df['Штуки'] >= 2]
        elif basket_filter == "Только повторные клиенты (LTV)":
            explorer_df = explorer_df[explorer_df['Client_ID'].isin(ltv_clients['Client_ID'])]
        elif basket_filter == "Только в пути / ПВЗ":
            explorer_df = explorer_df[explorer_df['Статус'].isin(['Доставляется', 'Ожидает в ПВЗ', 'Ожидает сборки', 'Ожидает отгрузки'])]
        elif basket_filter == "Только отмененные":
            explorer_df = explorer_df[explorer_df['Статус'] == 'Отменён']

        if search_query.strip():
            q = search_query.strip().lower()
            search_mask = (
                explorer_df['Номер заказа'].astype(str).str.lower().str.contains(q, na=False) |
                explorer_df['Номер отправления'].astype(str).str.lower().str.contains(q, na=False) |
                explorer_df['Client_ID'].astype(str).str.lower().str.contains(q, na=False) |
                explorer_df.get('Артикул', pd.Series(index=explorer_df.index)).astype(str).str.lower().str.contains(q, na=False) |
                explorer_df.get('Название товара', pd.Series(index=explorer_df.index)).astype(str).str.lower().str.contains(q, na=False) |
                explorer_df.get('Код этикетки', pd.Series(index=explorer_df.index)).astype(str).str.lower().str.contains(q, na=False)
            )
            explorer_df = explorer_df[search_mask]

        st.markdown(
            f"**Найдено записей:** `{len(explorer_df)}` &nbsp;|&nbsp; "
            f"**Уникальных заказов:** `{explorer_df['Номер заказа'].nunique()}` &nbsp;|&nbsp; "
            f"**Штук:** `{explorer_df['Штуки'].sum():.0f} шт.` &nbsp;|&nbsp; "
            f"**Сумма выборки:** `{fmt_money(explorer_df['Выручка'].sum())}`"
        )

        display_cols = [
            'Принят в обработку', 'Номер заказа', 'Номер отправления', 'Client_ID',
            'Логистика', 'Статус', 'Артикул', 'Тип_Чехла', 'Цвет товара',
            'Штуки', 'Выручка', 'Оплачено_покупателем', 'Цена_до_скидок',
            'Тип_Продвижения', 'Дней_в_пути', 'Дата доставки', '_file_name'
        ]
        avail_display_cols = [c for c in display_cols if c in explorer_df.columns]

        st.dataframe(
            explorer_df[avail_display_cols],
            column_config={
                "Принят в обработку": st.column_config.TextColumn("Дата и время заказа"),
                "Номер заказа": st.column_config.TextColumn("Номер заказа"),
                "Номер отправления": st.column_config.TextColumn("Отправление"),
                "Client_ID": st.column_config.TextColumn("ID Клиента"),
                "Логистика": st.column_config.TextColumn("Склад"),
                "Статус": st.column_config.TextColumn("Статус"),
                "Артикул": st.column_config.TextColumn("Артикул"),
                "Тип_Чехла": st.column_config.TextColumn("Товар"),
                "Цвет товара": st.column_config.TextColumn("Цвет"),
                "Штуки": st.column_config.NumberColumn("Шт.", format="%d"),
                "Выручка": st.column_config.NumberColumn("Сумма селлера", format="%d ₽"),
                "Оплачено_покупателем": st.column_config.NumberColumn("Оплатил клиент", format="%.0f ₽"),
                "Цена_до_скидок": st.column_config.NumberColumn("До скидки", format="%.0f ₽"),
                "Тип_Продвижения": st.column_config.TextColumn("Бустинг / Акция"),
                "Дней_в_пути": st.column_config.NumberColumn("Доставка (дн.)", format="%.1f дн."),
                "Дата доставки": st.column_config.TextColumn("Доставлено"),
                "_file_name": st.column_config.TextColumn("Источник (Файл)")
            },
            hide_index=True, use_container_width=True, height=600
        )

else:
    st.info("👆 Загрузите один или несколько файлов orders.csv (FBO) и postings.csv (FBS) за любые периоды — система автоматически склеит историю и обновит статусы...")
