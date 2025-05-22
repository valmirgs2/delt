import streamlit as st
import math
import requests
from PIL import Image, ImageDraw, ImageFont # ImageFont might not be used in this version
from io import BytesIO
from datetime import datetime, timedelta, time # Added time
import pytz # Added for timezone handling
import time as py_time # Renamed to avoid conflict with datetime.time
import random # Para simular dados da Ecowitt
import pandas as pd # Adicionado para o histórico
import altair as alt # Added for advanced charting

# --- Timezone Configuration ---
APP_TIMEZONE_STR = "America/Sao_Paulo" # UTC-3 (most of Brazil)
try:
    app_timezone = pytz.timezone(APP_TIMEZONE_STR)
except pytz.exceptions.UnknownTimeZoneError:
    st.error(f"Fuso horário desconhecido: {APP_TIMEZONE_STR}. Usando UTC.")
    app_timezone = pytz.utc

# --- Simulação do Firestore (substitua pela integração real) ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_firestore_simulado(dados):
    st.session_state.db_historico.append(dados)
    max_historico = 200
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico_do_firestore_simulado():
    return sorted(st.session_state.db_historico, key=lambda x: x.get('timestamp', ''), reverse=True)

# --- FUNÇÕES DE CÁLCULO ---
def calcular_temperatura_bulbo_umido_stull(t_bs, rh): # t_bs is the air temperature for calculation
    term1_factor = (rh + 8.313659)**0.5
    term1 = t_bs * math.atan(0.151977 * term1_factor)
    term2 = math.atan(t_bs + rh)
    term3 = math.atan(rh - 1.676331)
    term4_factor1 = rh**1.5
    term4_factor2 = math.atan(0.023101 * rh)
    term4 = 0.00391838 * term4_factor1 * term4_factor2
    constante_final = 4.686035
    t_w = term1 + term2 - term3 + term4 - constante_final
    return t_w

def calcular_delta_t_e_condicao(t_bs, rh): # t_bs is the air temperature for calculation
    if t_bs is None: # Explicitly check for None for t_bs
        return None, None, "Erro: Temperatura do Ar (t_bs) não fornecida.", None, None, None
    if not (0 <= rh <= 100):
        return None, None, "Erro: Umidade Relativa fora da faixa (0-100%).", None, None, None
    if not (0 <= t_bs <= 50):
        return None, None, f"Erro: Temperatura do Ar ({t_bs}°C) fora da faixa de cálculo (0-50°C).", None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w

        ponto_orvalho = t_bs - ((100 - rh) / 5.0)
        sensacao_termica = t_bs
        if rh >= 40:
            e = (rh/100) * 6.105 * math.exp((17.27 * t_bs) / (237.7 + t_bs))
            sensacao_termica = t_bs + 0.33 * e - 0.70 * 0
            if t_bs > 27:
                sensacao_termica = t_bs + 0.3 * ( (rh/100) * 6.105 * math.exp(17.27 * t_bs / (237.7 + t_bs)) - 10)

        if rh < 50 and t_bs > 25 : sensacao_termica = t_bs + (t_bs-25)/5
        elif rh > 70 and t_bs > 25: sensacao_termica = t_bs + (rh-70)/10 + (t_bs-25)/3

        condicao_texto = "-"
        descricao_condicao = ""
        if delta_t < 2:
            condicao_texto = "INADEQUADA"
            descricao_condicao = "Risco elevado de deriva e escorrimento."
        elif delta_t > 10:
            condicao_texto = "ARRISCADA"
            descricao_condicao = "Risco de evaporação excessiva das gotas."
        elif 2 <= delta_t <= 8:
            condicao_texto = "ADEQUADA"
            descricao_condicao = "Condições ideais para pulverização."
        else: # 8 < delta_t <= 10
            condicao_texto = "ATENÇÃO"
            descricao_condicao = f"Condição limite (Delta T {delta_t:.1f}°C)."

        return t_w, delta_t, condicao_texto, descricao_condicao, ponto_orvalho, sensacao_termica
    except Exception as e:
        return None, None, f"Erro no cálculo: {e}", None, None, None

# --- FUNÇÃO PARA DESENHAR PONTO E ÍCONE NO GRÁFICO ---
def desenhar_grafico_com_ponto(imagem_base_pil, temp_para_plotar, rh_usuario, url_icone):
    if imagem_base_pil is None:
        return None
    if temp_para_plotar is None: # Don't plot if temp is None
        return imagem_base_pil.copy()


    img_processada = imagem_base_pil.copy()
    draw = ImageDraw.Draw(img_processada)

    temp_min_grafico = 0.0
    temp_max_grafico = 50.0
    pixel_x_min_temp = 198
    pixel_x_max_temp = 880

    rh_min_grafico = 10.0
    rh_max_grafico = 100.0
    pixel_y_min_rh = 650
    pixel_y_max_rh = 108

    # Check if temp_para_plotar is within reasonable bounds for plotting
    if not (temp_min_grafico <= temp_para_plotar <= temp_max_grafico):
        st.warning(f"Temperatura para plotar ({temp_para_plotar}°C) fora da faixa do gráfico ({temp_min_grafico}-{temp_max_grafico}°C). Ponto não será desenhado.")
        return img_processada # Return a copy without the point if temp is out of displayable range

    if rh_usuario is not None: # rh_usuario can also be checked
        plotar_temp = max(temp_min_grafico, min(temp_para_plotar, temp_max_grafico))
        plotar_rh = max(rh_min_grafico, min(rh_usuario, rh_max_grafico))

        range_temp_grafico = temp_max_grafico - temp_min_grafico
        percent_temp = (plotar_temp - temp_min_grafico) / range_temp_grafico if range_temp_grafico != 0 else 0
        pixel_x_usuario = int(pixel_x_min_temp + percent_temp * (pixel_x_max_temp - pixel_x_min_temp))

        range_rh_grafico = rh_max_grafico - rh_min_grafico
        percent_rh = (plotar_rh - rh_min_grafico) / range_rh_grafico if range_rh_grafico != 0 else 0
        pixel_y_usuario = int(pixel_y_min_rh - percent_rh * (pixel_y_min_rh - pixel_y_max_rh))

        raio_ponto = 8
        cor_ponto = "red"
        draw.ellipse([(pixel_x_usuario - raio_ponto, pixel_y_usuario - raio_ponto),
                      (pixel_x_usuario + raio_ponto, pixel_y_usuario + raio_ponto)],
                     fill=cor_ponto, outline="black", width=1)
        try:
            response_icone = requests.get(url_icone, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            response_icone.raise_for_status()
            content_type_icone = response_icone.headers.get('content-type', '').lower()
            if not (content_type_icone.startswith('image/png') or \
                    content_type_icone.startswith('image/jpeg') or \
                    content_type_icone.startswith('image/gif') or \
                    content_type_icone.startswith('image/webp')):
                st.warning(f"O URL do ícone não parece ser uma imagem direta (Content-Type: {content_type_icone}).")
                return img_processada
            
            icone_img_original = Image.open(BytesIO(response_icone.content)).convert("RGBA")
            tamanho_icone_base = 35
            novo_tamanho_icone = int(tamanho_icone_base * 1.25)
            tamanho_icone = (novo_tamanho_icone, novo_tamanho_icone)
            icone_redimensionado = icone_img_original.resize(tamanho_icone, Image.Resampling.LANCZOS)
            pos_x_icone = pixel_x_usuario - tamanho_icone[0] // 2
            pos_y_icone = pixel_y_usuario - tamanho_icone[1] // 2
            img_processada.paste(icone_redimensionado, (pos_x_icone, pos_y_icone), icone_redimensionado)
        except Exception as e_icon:
            st.warning(f"Não foi possível carregar ou processar o ícone de marcação: {e_icon}")
    return img_processada

# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
st.set_page_config(page_title="Estação Meteorológica - BASE AGRO", layout="wide")
st.title("🌦️ Estação Meteorológica - BASE AGRO")

if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = datetime(1970, 1, 1, tzinfo=app_timezone)
if 'dados_atuais' not in st.session_state: st.session_state.dados_atuais = None
if 'imagem_grafico_atual' not in st.session_state: st.session_state.imagem_grafico_atual = None

url_grafico_base = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
url_icone_localizacao = "https://estudioweb.com.br/wp-content/uploads/2023/02/Emoji-Alvo-png.png"
INTERVALO_ATUALIZACAO_MINUTOS = 5

@st.cache_data(ttl=3600)
def carregar_imagem_base(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content)).convert("RGBA")
        return img
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao baixar a imagem base do gráfico: {e}")
        return None

imagem_base_pil = carregar_imagem_base(url_grafico_base)
if imagem_base_pil is None:
    st.error("A imagem de fundo do gráfico não pôde ser carregada. O aplicativo pode não funcionar corretamente.")

def buscar_dados_ecowitt_simulado():
    py_time.sleep(0.5)
    temp_inferior = round(random.uniform(0, 45), 1) # Base temperature (lower sensor)
    umid = round(random.uniform(10, 95), 1)
    # Simulate temp_superior to be generally usable by calculation (0-50 range)
    # If temp_inferior is 45, temp_superior could be up to 45 + 2.5 = 47.5 (ok)
    # If temp_inferior is 0, temp_superior could be 0 - 0.5 = -0.5 (will cause error in calc)
    # Let's make superior more robust for calculation range
    temp_superior_offset = random.uniform(-1.5, 2.5) # Smaller negative range
    temp_superior = round(temp_inferior + temp_superior_offset, 1)
    # Clip temp_superior to be within a range that calcular_delta_t_e_condicao typically accepts, e.g., 0-50
    temp_superior = max(0, min(temp_superior, 50))


    vento_vel = round(random.uniform(0, 25), 1)
    vento_raj = round(vento_vel + random.uniform(0, 15), 1)
    pressao = round(random.uniform(980, 1030), 1)
    direcoes_vento = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]
    vento_dir = random.choice(direcoes_vento)
    altitude = 314
    uv_index = random.randint(0, 11)
    luminosidade = random.randint(1000, 100000)
    radiacao_solar = random.randint(0, 1200)

    return {
        "temperature_c": temp_inferior, # Lower sensor temp
        "humidity_percent": umid,
        "temperature_superior_c": temp_superior, # Upper sensor temp
        "wind_speed_kmh": vento_vel, "wind_gust_kmh": vento_raj,
        "pressure_hpa": pressao, "wind_direction": vento_dir, "altitude_m": altitude,
        "uv_index": uv_index, "luminosity_lux": luminosidade, "solar_radiation_wm2": radiacao_solar
    }

def atualizar_dados_estacao():
    dados_ecowitt = buscar_dados_ecowitt_simulado()
    now_app_tz = datetime.now(app_timezone)

    if dados_ecowitt:
        temp_ar_inferior = dados_ecowitt["temperature_c"] # For display as "inferior"
        umid_rel = dados_ecowitt["humidity_percent"]
        temp_ar_superior = dados_ecowitt.get("temperature_superior_c") # For Delta T calculation

        # --- Delta T calculation now uses SUPERIOR temperature ---
        # Pass temp_ar_superior to the calculation function.
        # The function itself checks if temp_ar_superior (as t_bs) is None or out of range.
        t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = \
            calcular_delta_t_e_condicao(temp_ar_superior, umid_rel)

        # Determine temperature to use for plotting on the Delta T graph
        temp_para_plotar_grafico = None
        if delta_t is not None: # If Delta T calculation was successful
            temp_para_plotar_grafico = temp_ar_superior
        # else:
            # If Delta T failed (e.g. temp_ar_superior was bad),
            # temp_para_plotar_grafico remains None, and point won't be plotted.
            # Or, one could choose to plot temp_ar_inferior as a fallback marker.
            # For now, if Delta T calc fails, the point related to that calc (superior temp) is not plotted.

        if delta_t is not None: # Check if main calculation was successful
            dados_para_salvar = {
                "timestamp": now_app_tz.isoformat(),
                "temperature_c": temp_ar_inferior, # Store lower sensor temp
                "humidity_percent": umid_rel,
                "temperature_superior_c": temp_ar_superior, # Store upper sensor temp
                "wet_bulb_c": round(t_w, 2) if t_w is not None else None,
                "delta_t_c": round(delta_t, 2),
                "condition_text": condicao,
                "condition_description": desc_condicao,
                "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
                "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
            }
            dados_para_salvar.update(dados_ecowitt) # Add all other ecowitt data
            # Ensure specific fields are not accidentally overwritten if keys clash and we want ours
            dados_para_salvar["temperature_c"] = temp_ar_inferior
            dados_para_salvar["temperature_superior_c"] = temp_ar_superior


            salvar_dados_no_firestore_simulado(dados_para_salvar)
            st.session_state.dados_atuais = dados_para_salvar
            if imagem_base_pil:
                st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                    imagem_base_pil, temp_para_plotar_grafico, umid_rel, url_icone_localizacao
                )
            st.session_state.last_update_time = now_app_tz
            return True
        else:
            # Delta T calculation failed (e.g. t_bs was None or out of range)
            st.error(f"Falha no cálculo Delta T (usando Temp Superior {temp_ar_superior}°C): {condicao}")
            dados_erro = {
                "timestamp": now_app_tz.isoformat(),
                "temperature_c": temp_ar_inferior,
                "humidity_percent": umid_rel,
                "temperature_superior_c": temp_ar_superior,
                "wet_bulb_c": None, "delta_t_c": None,
                "condition_text": "ERRO CÁLCULO",
                "condition_description": desc_condicao, # This comes from calcular_delta_t_e_condicao
            }
            dados_erro.update(dados_ecowitt)
            dados_erro["temperature_c"] = temp_ar_inferior
            dados_erro["temperature_superior_c"] = temp_ar_superior

            st.session_state.dados_atuais = dados_erro
            if imagem_base_pil:
                 # Plot with temp_ar_inferior if superior caused error, or None
                st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                    imagem_base_pil, temp_ar_inferior, umid_rel, url_icone_localizacao # Fallback plot point
                )
            st.session_state.last_update_time = now_app_tz
            return False
    else:
        st.error("Não foi possível obter os dados da estação Ecowitt (simulado).")
        return False

agora_atual_app_tz = datetime.now(app_timezone)
if st.session_state.last_update_time.year == 1970 or \
   st.session_state.last_update_time < (agora_atual_app_tz - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    if st.session_state.last_update_time.year == 1970 and 'simulacao_info_mostrada' not in st.session_state:
        st.info("Usando dados simulados. Substitua `buscar_dados_ecowitt_simulado` pela sua integração real com a API Ecowitt.")
        st.session_state.simulacao_info_mostrada = True
    if atualizar_dados_estacao():
        if 'running_first_time' not in st.session_state:
            st.session_state.running_first_time = True
            # st.rerun() # Consider if rerun is needed on every auto-update
    # else:
        # print(f"DEBUG APP: Tentativa de atualização automática não bem-sucedida.")


last_update_display = 'Aguardando primeira atualização...'
if st.session_state.last_update_time.year > 1970:
    last_update_display = st.session_state.last_update_time.strftime('%d/%m/%Y %H:%M:%S %Z')
st.caption(f"Última atualização dos dados: {last_update_display}")
st.markdown("---")

st.subheader("Estação Meteorológica (Dados Atuais)")
dados = st.session_state.dados_atuais
if dados:
    st.markdown("##### 🌡️ Temperatura e Umidade")
    col_temp1, col_temp2 = st.columns(2)
    with col_temp1:
        st.metric(label="Temperatura do Ar (Inferior)", value=f"{dados.get('temperature_c', '-'):.1f} °C" if dados.get('temperature_c') is not None else "- °C")
        st.metric(label="Ponto de Orvalho", value=f"{dados.get('dew_point_c', '-'):.1f} °C" if dados.get('dew_point_c') is not None else "- °C")
    with col_temp2:
        st.metric(label="Umidade Relativa", value=f"{dados.get('humidity_percent', '-'):.1f} %" if dados.get('humidity_percent') is not None else "- %")
        st.metric(label="Sensação Térmica", value=f"{dados.get('feels_like_c', '-'):.1f} °C" if dados.get('feels_like_c') is not None else "- °C")

    # Display Superior Temperature if available, more prominently
    if 'temperature_superior_c' in dados and dados.get('temperature_superior_c') is not None:
        st.metric(label="Temperatura do Ar (Superior - p/ Delta T)", value=f"{dados.get('temperature_superior_c'):.1f} °C",
                  help="Esta temperatura é usada para o cálculo do Delta T.")


    st.markdown("##### 🌱 Delta T")
    # This section now implicitly uses Delta T calculated from the superior temperature
    condicao_atual_texto = dados.get('condition_text', '-')
    desc_condicao_atual = dados.get('condition_description', 'Aguardando dados...')
    cor_fundo_condicao = "lightgray"; cor_texto_condicao = "black"
    if condicao_atual_texto == "INADEQUADA": cor_fundo_condicao = "#FFA500"; cor_texto_condicao = "#FFFFFF"
    elif condicao_atual_texto == "ARRISCADA": cor_fundo_condicao = "#FF0000"; cor_texto_condicao = "#FFFFFF"
    elif condicao_atual_texto == "ADEQUADA": cor_fundo_condicao = "#00EE00"; cor_texto_condicao = "#FFFFFF"
    elif condicao_atual_texto == "ATENÇÃO": cor_fundo_condicao = "#FFA500"; cor_texto_condicao = "#FFFFFF"
    elif "ERRO" in condicao_atual_texto.upper() : cor_fundo_condicao = "#F8D7DA"; cor_texto_condicao = "#721C24"


    delta_t_val_num = dados.get('delta_t_c', None)
    delta_t_display_val = f"{delta_t_val_num:.2f}" if delta_t_val_num is not None else "-"

    st.markdown(f"""
    <div style='text-align: center; margin-bottom: 10px;'>
        <span style='font-size: 1.1em; font-weight: bold;'>Valor Delta T:</span><br>
        <span style='font-size: 2.2em; font-weight: bold; color: #007bff;'>{delta_t_display_val} °C</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style='background-color: {cor_fundo_condicao}; color: {cor_texto_condicao}; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 5px;'>
        <strong style='font-size: 1.1em;'>Condição Delta T: {condicao_atual_texto}</strong>
    </div>
    <p style='text-align: center; font-size: 0.85em; color: #555;'>{desc_condicao_atual}</p>
    """, unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("##### 💨 Vento e Pressão")
    col_vento1, col_vento2 = st.columns(2)
    vento_velocidade_atual = dados.get('wind_speed_kmh', 0.0)
    if vento_velocidade_atual is None: vento_velocidade_atual = 0.0


    condicao_vento_texto = "-"
    desc_condicao_vento = ""
    cor_fundo_vento = "lightgray"; cor_texto_vento = "black"

    if vento_velocidade_atual <= 3:
        condicao_vento_texto = "INADEQUADO"
        desc_condicao_vento = "Risco de inversão térmica (vento muito fraco)."
        cor_fundo_vento = "#FFA500"; cor_texto_vento = "#FFFFFF"
    elif 3 < vento_velocidade_atual <= 10:
        condicao_vento_texto = "EXCELENTE"
        desc_condicao_vento = "Condições ideais de vento."
        cor_fundo_vento = "#00EE00"; cor_texto_vento = "#FFFFFF"
    else: # > 10 km/h
        condicao_vento_texto = "MUITO PERIGOSO"
        desc_condicao_vento = "Risco de deriva (vento forte)."
        cor_fundo_vento = "#FF0000"; cor_texto_vento = "#FFFFFF"

    with col_vento1:
        st.metric(label="Vento Médio", value=f"{vento_velocidade_atual:.1f} km/h")
        st.metric(label="Pressão", value=f"{dados.get('pressure_hpa', '-'):.1f} hPa" if dados.get('pressure_hpa') is not None else "- hPa")
    with col_vento2:
        st.metric(label="Rajadas", value=f"{dados.get('wind_gust_kmh', '-'):.1f} km/h" if dados.get('wind_gust_kmh') is not None else "- km/h")
        st.metric(label="Direção Vento", value=f"{dados.get('wind_direction', '-')}")

    st.markdown(f"""
    <div style='background-color: {cor_fundo_vento}; color: {cor_texto_vento}; padding: 10px; border-radius: 5px; text-align: center; margin-top: 10px; margin-bottom: 5px;'>
        <strong style='font-size: 1.1em;'>Condição do Vento: {condicao_vento_texto}</strong>
    </div>
    <p style='text-align: center; font-size: 0.85em; color: #555;'>{desc_condicao_vento}</p>
    """, unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("##### 🌡️ Indicador de Inversão Térmica")
    temp_inferior_inv = dados.get('temperature_c', None)
    temp_superior_inv = dados.get('temperature_superior_c', None)
    vento_atual_kmh_inv = dados.get('wind_speed_kmh', None)

    # Displaying inversion check parameters clearly
    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric(label="Temp. Inferior (Inversão)", value=f"{temp_inferior_inv:.1f} °C" if temp_inferior_inv is not None else "N/D")
    with metric_cols[1]:
        st.metric(label="Temp. Superior (Inversão)", value=f"{temp_superior_inv:.1f} °C" if temp_superior_inv is not None else "N/D")
    with metric_cols[2]:
        st.metric(label="Vento (p/ Inversão)", value=f"{vento_atual_kmh_inv:.1f} km/h" if vento_atual_kmh_inv is not None else "N/D")


    status_inversao_texto = "Aguardando dados..."
    desc_inversao_texto = ""
    cor_fundo_inversao = "lightgray"
    cor_texto_inversao = "black"

    if temp_inferior_inv is not None and temp_superior_inv is not None and vento_atual_kmh_inv is not None:
        if temp_superior_inv < temp_inferior_inv:
            status_inversao_texto = "APLICAÇÃO LIBERADA"
            desc_inversao_texto = "Sem inversão térmica detectada."
            cor_fundo_inversao = "#00EE00"; cor_texto_inversao = "#FFFFFF"
        elif temp_superior_inv > temp_inferior_inv:
            if vento_atual_kmh_inv < 3:
                status_inversao_texto = "INVERSÃO TÉRMICA"
                desc_inversao_texto = "Não aplicar! Condições de inversão térmica."
                cor_fundo_inversao = "#FF0000"; cor_texto_inversao = "#FFFFFF"
            else:
                status_inversao_texto = "CUIDADO!"
                desc_inversao_texto = "Possível inversão térmica (sensor superior mais quente), mas vento acima de 3 km/h."
                cor_fundo_inversao = "#FFA500"; cor_texto_inversao = "#FFFFFF"
        else:
            status_inversao_texto = "CONDIÇÃO ESTÁVEL"
            desc_inversao_texto = "Temperaturas dos sensores superior e inferior estão iguais. Monitore o vento."
            cor_fundo_inversao = "lightgray"; cor_texto_inversao = "black"
    else:
        desc_inversao_texto = "Dados insuficientes para determinar a condição de inversão."

    st.markdown(f"""
    <div style='background-color: {cor_fundo_inversao}; color: {cor_texto_inversao}; padding: 10px; border-radius: 5px; text-align: center; margin-top:10px; margin-bottom: 5px;'>
        <strong style='font-size: 1.1em;'>{status_inversao_texto}</strong>
    </div>
    <p style='text-align: center; font-size: 0.85em; color: #555;'>{desc_inversao_texto}</p>
    """, unsafe_allow_html=True)
    st.markdown("---")

else:
    st.info("Aguardando dados da estação para exibir as condições atuais...")

if st.button("Forçar Atualização Manual Agora", key="btn_atualizar_dados"):
    if atualizar_dados_estacao():
        st.success("Dados atualizados manualmente!")
        st.rerun()
    else:
        st.error("Falha ao atualizar manualmente.")


st.subheader("Gráfico Delta T")
st.caption(f"O ponto no gráfico é baseado na Temperatura do Sensor Superior ({dados.get('temperature_superior_c', 'N/A'):.1f}°C) e Umidade Relativa ({dados.get('humidity_percent', 'N/A'):.1f}%) atuais, se disponíveis e válidos para cálculo de Delta T.")
imagem_para_exibir = st.session_state.get('imagem_grafico_atual')

if imagem_para_exibir:
    caption_text_img = "Gráfico de referência Delta T."
    if st.session_state.get('dados_atuais') and 'timestamp' in st.session_state.dados_atuais:
        try:
            ts_obj = datetime.fromisoformat(st.session_state.dados_atuais['timestamp'])
            caption_text_img = f"Ponto indicativo para dados de: {ts_obj.astimezone(app_timezone).strftime('%d/%m/%Y %H:%M:%S %Z')}"
        except Exception as e:
            caption_text_img = f"Ponto indicativo para dados de: {st.session_state.dados_atuais['timestamp']} (erro formatando: {e})"
    st.image(imagem_para_exibir, caption=caption_text_img, use_container_width=True)
elif imagem_base_pil: # Show base image if processed one is not available yet but base is
    st.image(imagem_base_pil, caption="Gráfico de referência Delta T (aguardando dados para ponto).", use_container_width=True)
else:
    st.warning("Imagem base do gráfico não disponível.")


st.markdown("---")
st.subheader("Histórico de Dados da Estação")
historico_bruto = carregar_historico_do_firestore_simulado()

if historico_bruto:
    df_historico = pd.DataFrame(historico_bruto)
    if not df_historico.empty and 'timestamp' in df_historico.columns:
        try:
            df_historico['timestamp_dt'] = pd.to_datetime(df_historico['timestamp'])
            df_historico['timestamp_dt'] = df_historico['timestamp_dt'].dt.tz_convert(app_timezone)
            df_historico = df_historico.sort_values(by='timestamp_dt', ascending=False)

            st.markdown("##### Últimos Registros")
            colunas_para_exibir = ['timestamp_dt', 'temperature_c', 'temperature_superior_c', 'humidity_percent', 'delta_t_c', 'condition_text', 'wind_speed_kmh', 'pressure_hpa']
            colunas_presentes = [col for col in colunas_para_exibir if col in df_historico.columns]
            df_display = df_historico[colunas_presentes].head(10).copy() # Use .copy() to avoid SettingWithCopyWarning

            novos_nomes_colunas = {
                'timestamp_dt': "Data/Hora", 'temperature_c': "Temp. Inf. (°C)",
                'temperature_superior_c': "Temp. Sup. (°C)", # Temp used for Delta T
                'humidity_percent': "Umid. Rel. (%)", 'delta_t_c': "Delta T (°C)",
                'condition_text': "Condição Delta T", 'wind_speed_kmh': "Vento (km/h)",
                'pressure_hpa': "Pressão (hPa)"}
            df_display.rename(columns=novos_nomes_colunas, inplace=True)

            if "Data/Hora" in df_display.columns:
                df_display.loc[:, "Data/Hora"] = df_display["Data/Hora"].dt.strftime('%d/%m/%Y %H:%M:%S %Z')
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("Tendências Recentes")

            df_chart_full_history = df_historico.set_index('timestamp_dt').sort_index()

            interval_options_map = {
                "Última 1 Hora": timedelta(hours=1), "Últimas 3 Horas": timedelta(hours=3),
                "Últimas 12 Horas": timedelta(hours=12), "Últimas 24 Horas": timedelta(days=1),
                "Últimos 3 Dias": timedelta(days=3), "Últimos 7 Dias": timedelta(days=7),
                "Todo o Histórico": None
            }
            
            st.write("Selecione o intervalo para os gráficos de tendências:")
            interval_choice = st.radio(
                "Intervalo:", options=list(interval_options_map.keys()) + ["Intervalo Personalizado"],
                horizontal=True, key="interval_selector"
            )

            now_for_filter = datetime.now(app_timezone)
            df_chart_filtered = pd.DataFrame()

            if interval_choice == "Intervalo Personalizado":
                col_start, col_end = st.columns(2)
                default_min_date = (now_for_filter - timedelta(days=7)).date()
                default_max_date = now_for_filter.date()
                if not df_chart_full_history.empty:
                    min_hist_date_dt = df_chart_full_history.index.min()
                    if pd.notnull(min_hist_date_dt): # Check if not NaT
                         min_hist_date = min_hist_date_dt.to_pydatetime().astimezone(app_timezone).date()
                         default_min_date = min_hist_date
                
                with col_start:
                    start_date_custom = st.date_input(
                        "Data Início", value=default_min_date,
                        min_value=(now_for_filter - timedelta(days=365*2)).date(),
                        max_value=now_for_filter.date(), key="start_date_picker"
                    )
                with col_end:
                    end_date_custom = st.date_input(
                        "Data Fim", value=default_max_date,
                        min_value=start_date_custom if start_date_custom else default_min_date,
                        max_value=now_for_filter.date(), key="end_date_picker"
                    )
                
                if start_date_custom and end_date_custom:
                    start_dt = app_timezone.localize(datetime.combine(start_date_custom, time.min))
                    end_dt = app_timezone.localize(datetime.combine(end_date_custom, time.max))
                    df_chart_filtered = df_chart_full_history[(df_chart_full_history.index >= start_dt) & (df_chart_full_history.index <= end_dt)]
            else:
                interval_delta = interval_options_map.get(interval_choice)
                if interval_delta is not None:
                    cutoff_time = now_for_filter - interval_delta
                    df_chart_filtered = df_chart_full_history[df_chart_full_history.index >= cutoff_time]
                else: 
                    df_chart_filtered = df_chart_full_history

            if not df_chart_filtered.empty:
                df_chart_display_altair = df_chart_filtered.reset_index()

                delta_t_chart = alt.Chart(df_chart_display_altair.dropna(subset=['delta_t_c'])).mark_line(point=True, interpolate='monotone').encode(
                    x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                    y=alt.Y('delta_t_c:Q', title='Delta T (°C)', scale=alt.Scale(zero=False)),
                    color=alt.condition(
                        alt.LogicalOrPredicate([
                            alt.LogicalAndPredicate([alt.datum.delta_t_c >= 0, alt.datum.delta_t_c < 2]),
                            alt.LogicalAndPredicate([alt.datum.delta_t_c > 8, alt.datum.delta_t_c <= 10])
                        ]),
                        alt.value('orange'),
                        alt.condition(
                            alt.LogicalAndPredicate([alt.datum.delta_t_c >= 2, alt.datum.delta_t_c <= 8]),
                            alt.value('green'),
                            alt.condition(alt.datum.delta_t_c > 10, alt.value('red'), alt.value('lightgray'))
                        )
                    ),
                    tooltip=[
                        alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                        alt.Tooltip('delta_t_c:Q', title='Delta T (°C)', format='.2f'),
                        alt.Tooltip('condition_text:N', title='Condição Delta T')
                    ]
                ).properties(title='Tendência Delta T (calculado com Temp. Superior)').interactive()
                st.altair_chart(delta_t_chart, use_container_width=True)

                # Chart for Temperature (Lower Sensor)
                temp_inf_chart = alt.Chart(df_chart_display_altair.dropna(subset=['temperature_c'])).mark_line(point=True, color='royalblue').encode(
                    x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                    y=alt.Y('temperature_c:Q', title='Temp. Ar Inf. (°C)', scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                             alt.Tooltip('temperature_c:Q', title='Temp. Inf. (°C)', format='.1f')]
                ).properties(title='Tendência Temperatura do Ar (Sensor Inferior)').interactive()
                st.altair_chart(temp_inf_chart, use_container_width=True)

                if 'temperature_superior_c' in df_chart_display_altair.columns:
                    temp_sup_chart = alt.Chart(df_chart_display_altair.dropna(subset=['temperature_superior_c'])).mark_line(point=True, color='orangered').encode(
                        x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                        y=alt.Y('temperature_superior_c:Q', title='Temp. Ar Sup. (°C)', scale=alt.Scale(zero=False)),
                        tooltip=[alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                                 alt.Tooltip('temperature_superior_c:Q', title='Temp. Sup. (°C)', format='.1f')]
                    ).properties(title='Tendência Temperatura do Ar (Sensor Superior)').interactive()
                    st.altair_chart(temp_sup_chart, use_container_width=True)

                humidity_chart = alt.Chart(df_chart_display_altair.dropna(subset=['humidity_percent'])).mark_line(point=True, color='forestgreen').encode(
                    x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                    y=alt.Y('humidity_percent:Q', title='Umid. Rel. (%)', scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                             alt.Tooltip('humidity_percent:Q', title='Umid. (%)', format='.1f')]
                ).properties(title='Tendência Umidade Relativa').interactive()
                st.altair_chart(humidity_chart, use_container_width=True)

                if 'wind_speed_kmh' in df_chart_display_altair.columns:
                    wind_chart = alt.Chart(df_chart_display_altair.dropna(subset=['wind_speed_kmh'])).mark_line(point=True, color='slategray').encode(
                        x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                        y=alt.Y('wind_speed_kmh:Q', title='Vento (km/h)', scale=alt.Scale(zero=True)),
                        tooltip=[alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                                 alt.Tooltip('wind_speed_kmh:Q', title='Vento (km/h)', format='.1f')]
                    ).properties(title='Tendência Velocidade do Vento').interactive()
                    st.altair_chart(wind_chart, use_container_width=True)
            else:
                st.info("Não há dados históricos suficientes para o intervalo selecionado para gerar gráficos de tendências.")

        except Exception as e_pd:
            st.error(f"Erro ao formatar histórico ou gerar gráficos: {e_pd}")
else:
    st.info("Nenhum histórico de dados encontrado.")

st.markdown("---")
st.markdown("""
**Notas:**
- **Cálculo Delta T:** Agora utiliza a **Temperatura do Sensor Superior**.
- **Indicador de Inversão Térmica:** Compara temperaturas dos sensores inferior e superior, e velocidade do vento.
- **Fuso Horário:** Todos os horários são exibidos em UTC-3 (America/Sao_Paulo).
- **Para uso real, substitua `buscar_dados_ecowitt_simulado()` e integre com sua API Ecowitt e um banco de dados persistente.**
""")
