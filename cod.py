import streamlit as st
import math
import requests
from PIL import Image, ImageDraw
from io import BytesIO
from datetime import datetime, timedelta, time
import pytz
import pandas as pd
import altair as alt

# --- Constantes Globais ---
APP_TIMEZONE_STR = "America/Sao_Paulo"
N_PONTOS_TRILHA_GRAFICO = 7 # Número de pontos na trilha do gráfico Delta T (incluindo o atual)
URL_ICONE_LOCALIZACAO = "https://estudioweb.com.br/wp-content/uploads/2023/02/Emoji-Alvo-png.png"
URL_GRAFICO_BASE = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
URL_LOGO_EMPRESA = "https://i.postimg.cc/9F8T5vBk/Whats-App-Image-2025-05-20-at-19-33-48.jpg"
INTERVALO_ATUALIZACAO_MINUTOS = 5

# --- Configuração de Fuso Horário ---
try:
    app_timezone = pytz.timezone(APP_TIMEZONE_STR)
except pytz.exceptions.UnknownTimeZoneError:
    st.error(f"Fuso horário desconhecido: {APP_TIMEZONE_STR}. Usando UTC.")
    app_timezone = pytz.utc

# --- Simulação do Firestore (Histórico) ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_historico(dados): # Renomeado para clareza
    st.session_state.db_historico.append(dados.copy()) # Salva uma cópia
    max_historico = 200 
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico(): # Renomeado para clareza
    return sorted([item.copy() for item in st.session_state.db_historico], key=lambda x: x.get('timestamp', ''), reverse=True)

# --- FUNÇÕES DE CÁLCULO (sem alterações) ---
def calcular_temperatura_bulbo_umido_stull(t_bs, rh):
    term1_factor = (rh + 8.313659)**0.5; term1 = t_bs * math.atan(0.151977 * term1_factor)
    term2 = math.atan(t_bs + rh); term3 = math.atan(rh - 1.676331)
    term4_factor1 = rh**1.5; term4_factor2 = math.atan(0.023101 * rh)
    term4 = 0.00391838 * term4_factor1 * term4_factor2
    return term1 + term2 - term3 + term4 - 4.686035

def calcular_delta_t_e_condicao(t_bs, rh):
    if t_bs is None: return None, None, "Erro: Temp. Superior não fornecida.", None, None, None
    if not isinstance(rh, (int, float)) or not (0 <= rh <= 100): return None, None, "Erro: Umidade inválida.", None, None, None
    if not isinstance(t_bs, (int, float)) or not (0 <= t_bs <= 50): return None, None, f"Erro: Temp. Superior ({t_bs}°C) fora da faixa.", None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh); delta_t = t_bs - t_w
        ponto_orvalho = t_bs - ((100 - rh) / 5.0); sensacao_termica = t_bs
        if rh >= 40:
            e = (rh/100) * 6.105 * math.exp((17.27 * t_bs) / (237.7 + t_bs))
            sensacao_termica = t_bs + 0.33 * e - 0.70 * 0
            if t_bs > 27: sensacao_termica = t_bs + 0.3 * ( (rh/100) * 6.105 * math.exp(17.27 * t_bs / (237.7 + t_bs)) - 10)
        if rh < 50 and t_bs > 25 : sensacao_termica = t_bs + (t_bs-25)/5
        elif rh > 70 and t_bs > 25: sensacao_termica = t_bs + (rh-70)/10 + (t_bs-25)/3
        if delta_t < 2: cond, desc = "INADEQUADA", "Risco de deriva/escorrimento."
        elif delta_t > 10: cond, desc = "ARRISCADA", "Risco de evaporação excessiva."
        elif 2 <= delta_t <= 8: cond, desc = "ADEQUADA", "Condições ideais."
        else: cond, desc = "ATENÇÃO", f"Limite (Delta T {delta_t:.1f}°C)."
        return t_w, delta_t, cond, desc, ponto_orvalho, sensacao_termica
    except Exception as e: return None, None, f"Erro cálculo: {e}", None, None, None

# --- NOVA FUNÇÃO PARA DESENHAR GRÁFICO COM TRILHA ---
def desenhar_grafico_com_trilha(imagem_base_pil, trilha_pontos_temp_rh, url_icone_ponto_atual):
    if imagem_base_pil is None: return None
    img_processada = imagem_base_pil.copy()
    draw = ImageDraw.Draw(img_processada)

    temp_min_g, temp_max_g = 0.0, 50.0; px_x_min, px_x_max = 198, 880
    rh_min_g, rh_max_g = 10.0, 100.0; px_y_min, px_y_max = 650, 108

    def calcular_coords_pixel(temp, rh):
        if temp is None or rh is None: return None
        if not (isinstance(temp, (int, float)) and isinstance(rh, (int, float))): return None
        # Não filtra aqui por estar fora da faixa, deixa o clipping visual cuidar disso
        
        plot_temp = max(temp_min_g, min(temp, temp_max_g)) # Clipa para os limites do gráfico
        plot_rh = max(rh_min_g, min(rh, rh_max_g))

        range_temp = temp_max_g - temp_min_g
        px_x = int(px_x_min + ((plot_temp - temp_min_g) / range_temp if range_temp != 0 else 0) * (px_x_max - px_x_min))
        
        range_rh = rh_max_g - rh_min_g
        px_y = int(px_y_min - ((plot_rh - rh_min_g) / range_rh if range_rh != 0 else 0) * (px_y_min - px_y_max))
        return (px_x, px_y)

    coordenadas_pixels_trilha = []
    for temp, rh in trilha_pontos_temp_rh:
        coords = calcular_coords_pixel(temp, rh)
        if coords:
            coordenadas_pixels_trilha.append(coords)

    if not coordenadas_pixels_trilha:
        return img_processada

    # Desenha linhas conectando todos os pontos da trilha
    if len(coordenadas_pixels_trilha) > 1:
        draw.line(coordenadas_pixels_trilha, fill="dodgerblue", width=2)

    # Desenha pontos históricos (todos menos o último, que é o atual)
    raio_historico = 4 # Aumentado um pouco
    cor_historico = "deepskyblue"
    for i in range(len(coordenadas_pixels_trilha) - 1):
        px, py = coordenadas_pixels_trilha[i]
        draw.ellipse([(px - raio_historico, py - raio_historico), 
                      (px + raio_historico, py + raio_historico)], 
                     fill=cor_historico, outline="#00008B", width=1) # Outline mais escuro

    # Desenha o ponto ATUAL (o último da lista) de forma destacada
    px_atual, py_atual = coordenadas_pixels_trilha[-1]
    raio_atual = 7
    cor_atual = "red"
    draw.ellipse([(px_atual - raio_atual, py_atual - raio_atual),
                  (px_atual + raio_atual, py_atual + raio_atual)],
                 fill=cor_atual, outline="darkred", width=1)

    # Desenha ícone no ponto ATUAL
    try:
        resp_icone = requests.get(url_icone_ponto_atual, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        resp_icone.raise_for_status()
        if any(ct in resp_icone.headers.get('content-type','').lower() for ct in ['png','jpeg','gif','webp']):
            icone_pil = Image.open(BytesIO(resp_icone.content)).convert("RGBA")
            tamanho_icone = (int(35*1.15), int(35*1.15)) # Ajuste o tamanho se necessário
            icone_redim = icone_pil.resize(tamanho_icone, Image.Resampling.LANCZOS)
            img_processada.paste(icone_redim, (px_atual - tamanho_icone[0]//2, py_atual - tamanho_icone[1]//2), icone_redim)
    except Exception: pass # Falha silenciosa no ícone
    
    return img_processada

# --- FUNÇÕES PARA BUSCAR DADOS REAIS DA ECOWITT (sem alterações na lógica interna) ---
def fetch_real_ecowitt_data():
    api_key = st.secrets.get("ECOWITT_API_KEY")
    app_key = st.secrets.get("ECOWITT_APPLICATION_KEY")
    mac_address = st.secrets.get("ECOWITT_MAC_ADDRESS")

    if not all([api_key, app_key, mac_address]):
        st.error("Credenciais da API Ecowitt não configuradas em .streamlit/secrets.toml")
        return None

    params = {
        "application_key": app_key, "api_key": api_key, "mac": mac_address,
        "temp_unitid": "1", "pressure_unitid": "3",
        "wind_speed_unitid": "7", "rainfall_unitid": "12", "call_back": "all",
    }
    api_url = "http://api.ecowitt.net/api/v3/device/real_time"

    try:
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status(); api_data = response.json()
        if api_data.get("code") == 0 and "data" in api_data:
            device_data = api_data["data"]
            mapped_data = {"temperature_c": None, "humidity_percent": None, "temperature_superior_c": None,
                           "wind_speed_kmh": None, "wind_gust_kmh": None, "pressure_hpa": None,
                           "wind_direction": None, "uv_index": None, "solar_radiation_wm2": None, "luminosity_lux": None}
            if "indoor" in device_data and "temperature" in device_data["indoor"]: mapped_data["temperature_c"] = device_data["indoor"]["temperature"].get("value")
            if "pressure" in device_data:
                mapped_data["pressure_hpa"] = device_data["pressure"].get("relative", {}).get("value")
                if mapped_data["pressure_hpa"] is None: mapped_data["pressure_hpa"] = device_data["pressure"].get("absolute", {}).get("value")
            if "outdoor" in device_data:
                if "temperature" in device_data["outdoor"]: mapped_data["temperature_superior_c"] = device_data["outdoor"]["temperature"].get("value")
                if "humidity" in device_data["outdoor"]: mapped_data["humidity_percent"] = device_data["outdoor"]["humidity"].get("value")
            if "wind" in device_data:
                if "wind_speed" in device_data["wind"]: mapped_data["wind_speed_kmh"] = device_data["wind"]["wind_speed"].get("value")
                if "wind_gust" in device_data["wind"]: mapped_data["wind_gust_kmh"] = device_data["wind"]["wind_gust"].get("value")
                if "wind_direction" in device_data["wind"]: mapped_data["wind_direction"] = convert_deg_to_cardinal(device_data["wind"]["wind_direction"].get("value"))
            if "solar_and_uvi" in device_data:
                if "solar" in device_data["solar_and_uvi"]: 
                    mapped_data["solar_radiation_wm2"] = device_data["solar_and_uvi"]["solar"].get("value")
                    if mapped_data["solar_radiation_wm2"] is not None:
                        try: mapped_data["luminosity_lux"] = float(str(mapped_data["solar_radiation_wm2"])) * 120 
                        except: pass
                if "uvi" in device_data["solar_and_uvi"]: mapped_data["uv_index"] = device_data["solar_and_uvi"]["uvi"].get("value")
            for key in mapped_data.keys():
                if mapped_data.get(key) is not None:
                    try: mapped_data[key] = float(str(mapped_data[key]))
                    except (ValueError, TypeError):
                        if not isinstance(mapped_data[key], str): mapped_data[key] = None
            return mapped_data
        else:
            st.error(f"API Ecowitt: {api_data.get('msg','Resp. inválida')} (Cod: {api_data.get('code','N/A')})")
            return None
    except requests.exceptions.RequestException as e: st.error(f"Conexão API Ecowitt: {e}"); return None
    except Exception as e: st.error(f"Processar API Ecowitt: {e}"); import traceback; print(f"Erro: {traceback.format_exc()}"); return None

# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
@st.cache_data(ttl=3600)
def load_image_from_url_cached(url): # Renomeado para evitar conflito se houver outra função com mesmo nome
    try:
        response = requests.get(url, timeout=10); response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception as e: print(f"Erro img {url}: {e}"); return None

logo_pil = load_image_from_url_cached(URL_LOGO_EMPRESA)
imagem_base_pil = load_image_from_url_cached(URL_GRAFICO_BASE)
if imagem_base_pil: imagem_base_pil = imagem_base_pil.convert("RGBA")

st.set_page_config(page_title="Estação Meteorológica BASE AGRO", layout="wide", initial_sidebar_state="collapsed")

col_logo_main, col_title_main = st.columns([1, 6])
with col_logo_main:
    if logo_pil: st.image(logo_pil, width=100)
with col_title_main:
    st.title("Estação Meteorológica BASE AGRO")
    st.caption("Monitoramento de condições para pulverização agrícola eficiente e segura.")

if 'last_update_time' not in st.session_state: st.session_state.last_update_time = datetime(1970,1,1,tzinfo=app_timezone)
if 'dados_atuais' not in st.session_state: st.session_state.dados_atuais = {}
if 'imagem_grafico_atual' not in st.session_state: st.session_state.imagem_grafico_atual = None


def atualizar_dados_estacao():
    dados_ecowitt = fetch_real_ecowitt_data()
    now_app_tz = datetime.now(app_timezone)

    if dados_ecowitt is None:
        st.warning("Não foi possível buscar dados reais da estação.")
        return False

    temp_ar_inferior = dados_ecowitt.get("temperature_c")
    umid_rel_superior = dados_ecowitt.get("humidity_percent")
    temp_ar_superior = dados_ecowitt.get("temperature_superior_c")

    t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = \
        calcular_delta_t_e_condicao(temp_ar_superior, umid_rel_superior)

    dados_completos = {
        "timestamp": now_app_tz.isoformat(), "temperature_c": temp_ar_inferior,
        "temperature_superior_c": temp_ar_superior, "humidity_percent": umid_rel_superior,
        "wet_bulb_c": round(t_w,2) if t_w is not None else None, "delta_t_c": round(delta_t,2) if delta_t is not None else None,
        "condition_text": condicao if delta_t is not None else "ERRO CÁLCULO", "condition_description": desc_condicao,
        "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
        "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
        "wind_speed_kmh": dados_ecowitt.get("wind_speed_kmh"), "wind_gust_kmh": dados_ecowitt.get("wind_gust_kmh"),
        "wind_direction": dados_ecowitt.get("wind_direction"), "pressure_hpa": dados_ecowitt.get("pressure_hpa"),
        "uv_index": dados_ecowitt.get("uv_index"), "solar_radiation_wm2": dados_ecowitt.get("solar_radiation_wm2"),
        "luminosity_lux": dados_ecowitt.get("luminosity_lux"),
    }
    if delta_t is None and desc_condicao: st.error(f"Falha cálculo Delta T: {desc_condicao}")

    salvar_dados_no_historico(dados_completos)
    st.session_state.dados_atuais = dados_completos
    
    if imagem_base_pil:
        historico_recente_cru = carregar_historico() # Carrega todo histórico (novo primeiro)
        
        trilha_para_plotar_temp_rh = []
        if historico_recente_cru:
            # Pega os N mais recentes para a trilha
            pontos_para_trilha = historico_recente_cru[:N_PONTOS_TRILHA_GRAFICO]
            pontos_para_trilha.reverse() # Ordem cronológica (mais antigo para mais novo)

            for record in pontos_para_trilha:
                temp_s = record.get("temperature_superior_c")
                rh_s = record.get("humidity_percent") # Umidade do Wittboy
                if temp_s is not None and rh_s is not None:
                    trilha_para_plotar_temp_rh.append((temp_s, rh_s))
        
        # Se não houver histórico, mas tiver dados atuais válidos, plota só o atual como "trilha" de 1 ponto
        if not trilha_para_plotar_temp_rh and temp_ar_superior is not None and umid_rel_superior is not None:
            trilha_para_plotar_temp_rh.append((temp_ar_superior, umid_rel_superior))

        if trilha_para_plotar_temp_rh: # Se houver pontos para a trilha
            st.session_state.imagem_grafico_atual = desenhar_grafico_com_trilha(
                imagem_base_pil, trilha_para_plotar_temp_rh, URL_ICONE_LOCALIZACAO
            )
        elif imagem_base_pil: # Sem trilha, mas com imagem base
             st.session_state.imagem_grafico_atual = imagem_base_pil.copy() 
        else: # Sem nada
             st.session_state.imagem_grafico_atual = None
            
    st.session_state.last_update_time = now_app_tz
    return delta_t is not None

# --- Interface Streamlit (com as alterações de layout solicitadas anteriormente) ---
if st.session_state.last_update_time.year == 1970 or \
   st.session_state.last_update_time < (datetime.now(app_timezone) - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    atualizar_dados_estacao()

last_update_dt = st.session_state.last_update_time
last_update_str = last_update_dt.strftime('%d/%m/%Y %H:%M:%S') if last_update_dt.year > 1970 else 'Aguardando...'
st.caption(f"Última atualização: {last_update_str} (Horário Local: {APP_TIMEZONE_STR})")
st.markdown("---")

st.subheader("Condições Atuais da Estação")
dados = st.session_state.dados_atuais
if dados: 
    st.markdown("##### 🌡️ Temperatura e Umidade")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        if dados.get('temperature_superior_c') is not None:
            st.metric("Temperatura", f"{dados.get('temperature_superior_c'):.1f} °C", help="Temperatura do ar (Wittboy). Usada para Delta T.")
        else: st.metric("Temperatura", "- °C")
        st.metric("Ponto de Orvalho", f"{dados.get('dew_point_c', '-'):.1f} °C" if dados.get('dew_point_c') is not None else "- °C")
    with col_t2:
        st.metric("Umidade Relativa", f"{dados.get('humidity_percent', '-'):.1f} %" if dados.get('humidity_percent') is not None else "- %", help="Umidade (Wittboy).")
        st.metric("Sensação Térmica", f"{dados.get('feels_like_c', '-'):.1f} °C" if dados.get('feels_like_c') is not None else "- °C")
    st.markdown("---")

    dt_val = dados.get('delta_t_c'); dt_cond = dados.get('condition_text', '-'); dt_desc = dados.get('condition_description', 'Aguardando...')
    dt_map = {"INADEQUADA":"#FFA500","ARRISCADA":"#FF0000","ADEQUADA":"#00CC66","ATENÇÃO":"#FFA500"}
    dt_bg = dt_map.get(dt_cond, "#F8D7DA" if "ERRO" in str(dt_cond).upper() else "lightgray")
    dt_txt = "#FFFFFF" if dt_cond in dt_map else ("#721C24" if "ERRO" in str(dt_cond).upper() else "black")
    st.markdown(f"<div style='text-align:center;margin-bottom:10px'><span style='font-size:1.1em;font-weight:bold'>Delta T (Base T.Sup.):</span><br><span style='font-size:2.2em;font-weight:bold;color:#007bff'>{dt_val:.2f}°C</span></div>" if dt_val is not None else "<div style='text-align:center;margin-bottom:10px'><span style='font-size:1.1em;font-weight:bold'>Delta T:</span><br><span style='font-size:2.2em;font-weight:bold;color:gray'>-</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='background-color:{dt_bg};color:{dt_txt};padding:10px;border-radius:5px;text-align:center;margin-bottom:5px'><strong style='font-size:1.1em'>Condição Delta T: {dt_cond}</strong></div><p style='text-align:center;font-size:0.85em;color:#555'>{dt_desc}</p>", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("##### 💨 Vento e Pressão")
    col_v1, col_v2 = st.columns(2)
    v_vel = dados.get('wind_speed_kmh',0.0) if dados.get('wind_speed_kmh') is not None else 0.0
    vc,vd,vbg,vtxt = "-","","lightgray","black"
    if v_vel <= 3: vc,vd,vbg,vtxt = "INADEQUADO","Risco inversão.","#FFA500","#FFFFFF"
    elif 3 < v_vel <= 12: vc,vd,vbg,vtxt = "EXCELENTE","Vento ideal.","#00CC66","#FFFFFF"
    else: vc,vd,vbg,vtxt = "PERIGOSO","Risco deriva.","#FF0000","#FFFFFF"
    col_v1.metric("Vento Médio", f"{v_vel:.1f} km/h")
    col_v1.metric("Pressão", f"{dados.get('pressure_hpa', '-'):.1f} hPa" if dados.get('pressure_hpa') is not None else "-")
    col_v2.metric("Rajadas", f"{dados.get('wind_gust_kmh', '-'):.1f} km/h" if dados.get('wind_gust_kmh') is not None else "-")
    col_v2.metric("Direção Vento", f"{dados.get('wind_direction', '-')}")
    st.markdown(f"<div style='background-color:{vbg};color:{vtxt};padding:10px;border-radius:5px;text-align:center;margin-top:10px;margin-bottom:5px'><strong style='font-size:1.1em'>Cond. Vento: {vc}</strong></div><p style='text-align:center;font-size:0.85em;color:#555'>{vd}</p>", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("##### 🌡️ Indicador de Inversão Térmica")
    t_inf,t_sup,v_inv = dados.get('temperature_c'),dados.get('temperature_superior_c'),dados.get('wind_speed_kmh')
    inv_cols = st.columns(3)
    inv_cols[0].metric("Temperatura Inferior", f"{t_inf:.1f}°C" if t_inf is not None else "N/D", help="Temp. medida pelo GW2000 (base).")
    inv_cols[1].metric("Temperatura Superior", f"{t_sup:.1f}°C" if t_sup is not None else "N/D", help="Temp. medida pelo Wittboy (topo).")
    inv_cols[2].metric("Vento Atual", f"{v_inv:.1f} km/h" if v_inv is not None else "N/D")
    s_inv,d_inv,bg_inv,txt_inv="Aguardando...","","lightgray","black"
    if all(val is not None for val in [t_inf,t_sup,v_inv]):
        if t_sup < t_inf: s_inv,d_inv,bg_inv,txt_inv="LIBERADA","Sem inversão.","#00CC66","#FFFFFF"
        elif t_sup > t_inf:
            if v_inv < 3: s_inv,d_inv,bg_inv,txt_inv="INVERSÃO TÉRMICA","Não aplicar!","#FF0000","#FFFFFF"
            else: s_inv,d_inv,bg_inv,txt_inv="CUIDADO!","Possível inversão.","#FFA500","#FFFFFF"
        else: s_inv,d_inv="ESTÁVEL","Temps iguais."
    else: d_inv="Dados insuficientes."
    st.markdown(f"<div style='background-color:{bg_inv};color:{txt_inv};padding:10px;border-radius:5px;text-align:center;margin-top:10px;margin-bottom:5px'><strong style='font-size:1.1em'>{s_inv}</strong></div><p style='text-align:center;font-size:0.85em;color:#555'>{d_inv}</p>", unsafe_allow_html=True)
    st.markdown("---")
else:
    st.info("Aguardando dados da estação para exibir as condições atuais...")

if st.button("🔄 Forçar Atualização Manual", help="Busca novos dados da estação Ecowitt."):
    if atualizar_dados_estacao(): st.success("Dados atualizados!")
    else: st.error("Falha ao buscar ou processar dados da estação.")
    st.rerun()

st.subheader("Gráfico Delta T de Referência")
img_exibir_trilha = st.session_state.get('imagem_grafico_atual')
if img_exibir_trilha:
    ts_str = datetime.fromisoformat(dados['timestamp']).astimezone(app_timezone).strftime('%d/%m/%Y %H:%M:%S') if dados and dados.get('timestamp') else "desconhecida"
    st.image(img_exibir_trilha, caption=f"Trilha plotada para dados até: {ts_str}", use_container_width=True)
elif imagem_base_pil:
    st.image(imagem_base_pil, caption="Gráfico de referência (aguardando dados para trilha).", use_container_width=True)
else:
    st.warning("Imagem base do gráfico Delta T não pôde ser carregada.")
st.markdown("---")

st.subheader("Histórico de Dados da Estação")
hist_bruto = carregar_historico()
if hist_bruto:
    df_hist = pd.DataFrame(hist_bruto)
    if not df_hist.empty and 'timestamp' in df_hist.columns:
        try:
            df_hist['timestamp_dt'] = pd.to_datetime(df_hist['timestamp'].astype(str), errors='coerce')
            df_hist.dropna(subset=['timestamp_dt'], inplace=True)
            if df_hist['timestamp_dt'].dt.tz is None: df_hist['timestamp_dt'] = df_hist['timestamp_dt'].dt.tz_localize('UTC').dt.tz_convert(app_timezone)
            else: df_hist['timestamp_dt'] = df_hist['timestamp_dt'].dt.tz_convert(app_timezone)
            df_hist = df_hist.sort_values(by='timestamp_dt', ascending=False)

            st.markdown("##### Últimos Registros")
            cols_ver = ['timestamp_dt','temperature_c','temperature_superior_c','humidity_percent','delta_t_c','condition_text','wind_speed_kmh']
            df_show = df_hist[[c for c in cols_ver if c in df_hist.columns]].head(10).copy()
            map_n = {'timestamp_dt':"Data/Hora",'temperature_c':"T.Inf(°C)",'temperature_superior_c':"T.Sup(°C)",'humidity_percent':"UR(%)",'delta_t_c':"ΔT(°C)",'condition_text':"Cond.ΔT",'wind_speed_kmh':"Vento(km/h)"}
            df_show.rename(columns=map_n, inplace=True)
            if "Data/Hora" in df_show.columns: df_show.loc[:,"Data/Hora"] = df_show["Data/Hora"].dt.strftime('%d/%m/%y %H:%M')
            st.dataframe(df_show, use_container_width=True, hide_index=True)
            st.markdown("---")

            st.subheader("Tendências Recentes")
            df_chart_base = df_hist.set_index('timestamp_dt').sort_index()
            opts_int_trend = {"1 H":1,"3 H":3,"12 H":12,"24 H":24,"3 D":72,"7 D":168,"Tudo":None}
            sel_int_trend = st.radio("Intervalo Gráficos:", list(opts_int_trend.keys())+["Custom"], horizontal=True, key="sel_int_trend")
            df_chart_plot = pd.DataFrame(); now_f = datetime.now(app_timezone)

            if sel_int_trend == "Custom":
                pick_cols = st.columns(2) 
                if len(pick_cols) == 2:
                    cs, ce = pick_cols
                    min_h_dt = (now_f - timedelta(days=7)).date()
                    if not df_chart_base.empty and pd.notna(df_chart_base.index.min()): min_h_dt = df_chart_base.index.min().date()
                    s_v = st.session_state.get('d_s_val',min_h_dt); e_v = st.session_state.get('d_e_val',now_f.date())
                    d_s = cs.date_input("Início",value=s_v,min_value=(now_f-timedelta(days=730)).date(),max_value=now_f.date(),key="d_s_ui")
                    if d_s: st.session_state.d_s_val = d_s
                    if d_s and e_v < d_s: e_v = d_s
                    d_e = ce.date_input("Fim",value=e_v,min_value=d_s if d_s else (now_f-timedelta(days=730)).date(),max_value=now_f.date(),key="d_e_ui")
                    if d_e: st.session_state.d_e_val = d_e
                    if d_s and d_e:
                        sdt = app_timezone.localize(datetime.combine(d_s,time.min)); edt = app_timezone.localize(datetime.combine(d_e,time.max))
                        df_chart_plot = df_chart_base[(df_chart_base.index>=sdt)&(df_chart_base.index<=edt)]
                    else: df_chart_plot = pd.DataFrame()
                else: st.error("Falha colunas datas."); df_chart_plot = pd.DataFrame()
            else:
                h = opts_int_trend.get(sel_int_trend)
                if h is not None: df_chart_plot = df_chart_base[df_chart_base.index >= (now_f - timedelta(hours=h))]
                else: df_chart_plot = df_chart_base
            
            if not df_chart_plot.empty:
                df_altair_plot = df_chart_plot.reset_index()
                common_x_alt = alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %Hh'))
                tooltip_ts_alt = alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m %H:%M')
                delta_t_altair = alt.Chart(df_altair_plot.dropna(subset=['delta_t_c'])).mark_line(point=alt.OverlayMarkDef(size=20),interpolate='monotone').encode(
                    x=common_x_alt, y=alt.Y('delta_t_c:Q', title='ΔT (°C)'),
                    color=alt.condition(alt.LogicalOrPredicate(predicates=[alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c>=0,alt.datum.delta_t_c<2]),alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c>8,alt.datum.delta_t_c<=10])]),alt.value('orange'),
                                      alt.condition(alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c>=2,alt.datum.delta_t_c<=8]),alt.value('#00CC66'),
                                                    alt.condition(alt.datum.delta_t_c>10,alt.value('red'),alt.value('lightgray')))),
                    tooltip=[tooltip_ts_alt, alt.Tooltip('delta_t_c:Q',title='ΔT(°C)',format='.2f'),alt.Tooltip('condition_text:N',title='Cond.ΔT')]
                ).properties(title='Tendência Delta T (base T.Superior)').interactive()
                st.altair_chart(delta_t_altair, use_container_width=True)
                for col_name, chart_title, color_val in [('temperature_c','T.Inf.(°C)','royalblue'),('temperature_superior_c','T.Sup.(°C)','orangered'),('humidity_percent','UR(%)','forestgreen'),('wind_speed_kmh','Vento(km/h)','slategray')]:
                    if col_name in df_altair_plot.columns:
                        chart_obj = alt.Chart(df_altair_plot.dropna(subset=[col_name])).mark_line(point=True,color=color_val).encode(
                            x=common_x_alt,y=alt.Y(f'{col_name}:Q',title=chart_title),tooltip=[tooltip_ts_alt,alt.Tooltip(f'{col_name}:Q',title=chart_title,format='.1f')]
                        ).properties(title=f'Tendência {chart_title}').interactive()
                        st.altair_chart(chart_obj, use_container_width=True)
            else: st.info("Sem dados históricos para o intervalo selecionado.")
        except Exception as e_pd_altair:
            st.error(f"Erro ao formatar histórico ou gerar gráficos: {e_pd_altair}")
            import traceback; print(f"Erro Pandas/Altair: {e_pd_altair}\n{traceback.format_exc()}")
else: st.info("Nenhum histórico de dados encontrado.")

st.markdown("---")
st.markdown("""
**Notas:**
- **Delta T:** Calculado com a **Temperatura do Sensor Superior** (Wittboy).
- **Temperatura Inferior:** Medida pelo gateway **GW2000**.
- **Inversão Térmica:** Avaliada comparando T. Inferior, T. Superior e Vento.
- **Horários:** Exibidos no fuso horário local da aplicação (`America/Sao_Paulo`).
- **Dados Reais:** O aplicativo agora tenta buscar dados da sua estação Ecowitt via API.
""")
