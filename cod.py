import streamlit as st
import math
from PIL import Image, ImageFilter # Adicionado Pillow
import requests # Adicionado para carregar imagem de URL
from io import BytesIO # Adicionado para carregar imagem de URL

# --- Funções de Manipulação de Imagem ---
def carregar_imagem_de_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        return img
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de rede ao carregar imagem de {url}: {e}")
        return None
    except Exception as e:
        st.error(f"Erro ao abrir imagem de {url}: {e}")
        return None

def mapear_valor(valor, de_min, de_max, para_min, para_max):
    """Mapeia um valor de uma faixa para outra (interpolação linear)."""
    valor_clamped = max(de_min, min(valor, de_max))
    if (de_max - de_min) == 0:
        return para_min
    return (valor_clamped - de_min) * (para_max - para_min) / (de_max - de_min) + para_min

def sobrepor_alvo_no_grafico(img_grafico_base, img_alvo_url, temp_para_plotar, umidade_para_plotar, params_grafico):
    # --- Início DEBUG dentro de sobrepor_alvo_no_grafico ---
    st.markdown("---")
    st.subheader("DEBUG: `sobrepor_alvo_no_grafico`")

    if img_grafico_base is None:
        st.error("DEBUG Fun_Sobrepor: img_grafico_base é None.")
        st.markdown("---")
        return None

    st.write(f"DEBUG Fun_Sobrepor: Valores de entrada: Temp={temp_para_plotar}, Umidade={umidade_para_plotar}")
    st.write(f"DEBUG Fun_Sobrepor: Dimensões do gráfico base original: {img_grafico_base.size}")

    img_alvo = carregar_imagem_de_url(img_alvo_url)
    if img_alvo is None:
        st.warning("DEBUG Fun_Sobrepor: Não foi possível carregar a imagem do alvo DENTRO da função.")
        st.markdown("---")
        return img_grafico_base.copy()

    st.write(f"DEBUG Fun_Sobrepor: Alvo carregado: {img_alvo.size}, Modo: {img_alvo.mode}")

    tamanho_alvo = (40, 40)
    try:
        img_alvo_redimensionado = img_alvo.resize(tamanho_alvo, Image.Resampling.LANCZOS) # Use nova variável
        st.write(f"DEBUG Fun_Sobrepor: Alvo redimensionado para: {img_alvo_redimensionado.size}")
    except Exception as e:
        st.error(f"DEBUG Fun_Sobrepor: Erro ao redimensionar imagem do alvo: {e}")
        st.markdown("---")
        return img_grafico_base.copy()

    coord_x = mapear_valor(
        temp_para_plotar,
        params_grafico["temp_min_dado_eixo_x"], params_grafico["temp_max_dado_eixo_x"],
        params_grafico["temp_pixel_min_eixo_x"], params_grafico["temp_pixel_max_eixo_x"]
    )
    coord_y = mapear_valor(
        umidade_para_plotar,
        params_grafico["umidade_min_dado_eixo_y"], params_grafico["umidade_max_dado_eixo_y"],
        params_grafico["umidade_pixel_para_min_dado_eixo_y"], params_grafico["umidade_pixel_para_max_dado_eixo_y"]
    )
    st.write(f"DEBUG Fun_Sobrepor: Coordenadas calculadas (centro do alvo): X={coord_x:.2f}, Y={coord_y:.2f}")

    pos_x_paste = int(coord_x - img_alvo_redimensionado.width / 2)
    pos_y_paste = int(coord_y - img_alvo_redimensionado.height / 2)
    st.write(f"DEBUG Fun_Sobrepor: Posição de colagem (canto sup. esq. do alvo): X_paste={pos_x_paste}, Y_paste={pos_y_paste}")

    img_com_alvo = img_grafico_base.copy()
    if img_alvo_redimensionado.mode == 'RGBA':
        img_com_alvo.paste(img_alvo_redimensionado, (pos_x_paste, pos_y_paste), img_alvo_redimensionado)
    else:
        img_com_alvo.paste(img_alvo_redimensionado, (pos_x_paste, pos_y_paste))
    
    st.write("DEBUG Fun_Sobrepor: Colagem (paste) do alvo concluída.")
    st.markdown("---")
    # --- Fim DEBUG dentro de sobrepor_alvo_no_grafico ---
    return img_com_alvo

# --- Suas funções de cálculo (exatamente como antes) ---
def calcular_temperatura_bulbo_umido_stull(t_bs, rh):
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

def calcular_delta_t(t_bs, rh):
    if not (0 <= rh <= 100):
        return "Erro: A umidade relativa (entrada) deve estar entre 0 e 100%.", None
    if t_bs < -50 or t_bs > 60:
        return "Erro: Temperatura de bulbo seco (entrada) fora da faixa esperada (-50 a 60°C).", None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w
        return delta_t, t_w
    except Exception as e:
        return f"Erro no cálculo: {e}", None

# --- Interface Streamlit ---
st.set_page_config(page_title="Calculadora Delta T", layout="wide")
st.title("💧 Calculadora de Delta T para Pulverização")
st.caption("Baseada na fórmula de Stull. O ponto no gráfico indica a condição de entrada.")

# --- Configuração do Gráfico e Alvo ---
URL_GRAFICO_BASE = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
URL_ALVO_EMOJI = "https://i.postimg.cc/wv3SQqLg/Emoji-Alvo-png-1.webp" # URL ATUALIZADA

# --- Início do código de teste de carregamento de imagem (ADICIONADO PARA DEBUG) ---
st.markdown("---")
st.subheader("--- Teste de Carregamento de Imagens (Início da Página) ---")

st.write("Tentando carregar imagem do GRÁFICO BASE:")
img_base_teste_inicial = carregar_imagem_de_url(URL_GRAFICO_BASE)
if img_base_teste_inicial:
    st.image(img_base_teste_inicial, caption="DEBUG: Teste GRÁFICO BASE Carregado OK", width=150) # Menor para não ocupar tanto espaço
    st.write(f"DEBUG: Dimensões Gráfico Base: {img_base_teste_inicial.size}, Modo: {img_base_teste_inicial.mode}")
else:
    st.error("DEBUG: FALHA ao carregar imagem do GRÁFICO BASE para teste.")

st.write("Tentando carregar imagem do ALVO:")
img_alvo_teste_inicial = carregar_imagem_de_url(URL_ALVO_EMOJI)
if img_alvo_teste_inicial:
    st.image(img_alvo_teste_inicial, caption="DEBUG: Teste ALVO Carregado OK", width=80)
    st.write(f"DEBUG: Dimensões Alvo: {img_alvo_teste_inicial.size}, Modo: {img_alvo_teste_inicial.mode}")
else:
    st.error("DEBUG: FALHA ao carregar imagem do ALVO para teste.")
st.markdown("---")
# --- Fim do código de teste ---

PARAMETROS_GRAFICO = {
    "temp_min_dado_eixo_x": 0.0,
    "temp_max_dado_eixo_x": 50.0,
    "temp_pixel_min_eixo_x": 443,
    "temp_pixel_max_eixo_x": 1965,
    "umidade_min_dado_eixo_y": 10.0,
    "umidade_max_dado_eixo_y": 100.0,
    "umidade_pixel_para_min_dado_eixo_y": 1450,
    "umidade_pixel_para_max_dado_eixo_y": 242,
}

@st.cache_data
def carregar_grafico_base_cache(url):
    return carregar_imagem_de_url(url)

img_grafico_base_original = carregar_grafico_base_cache(URL_GRAFICO_BASE)

col_entrada, col_resultados = st.columns(2)

with col_entrada:
    st.header("Entrada de Dados")
    temp_bulbo_seco_input = st.number_input(
        "Temperatura de Bulbo Seco (°C):",
        min_value=PARAMETROS_GRAFICO["temp_min_dado_eixo_x"],
        max_value=PARAMETROS_GRAFICO["temp_max_dado_eixo_x"],
        value=25.0, step=0.1, format="%.1f",
        help=f"Valores entre {PARAMETROS_GRAFICO['temp_min_dado_eixo_x']}°C e {PARAMETROS_GRAFICO['temp_max_dado_eixo_x']}°C."
    )
    umidade_relativa_input = st.number_input(
        "Umidade Relativa (%):",
        min_value=PARAMETROS_GRAFICO["umidade_min_dado_eixo_y"],
        max_value=PARAMETROS_GRAFICO["umidade_max_dado_eixo_y"],
        value=60.0, step=0.1, format="%.1f",
        help=f"Valores entre {PARAMETROS_GRAFICO['umidade_min_dado_eixo_y']}% e {PARAMETROS_GRAFICO['umidade_max_dado_eixo_y']}%."
    )
    calcular_btn = st.button("Calcular Delta T e Mostrar no Gráfico", type="primary")

with col_resultados:
    st.header("Resultados e Gráfico")
    if calcular_btn:
        resultado_delta_t, t_w_calculada = calcular_delta_t(temp_bulbo_seco_input, umidade_relativa_input)

        if isinstance(resultado_delta_t, str):
            st.error(resultado_delta_t)
            st.metric(label="Temperatura Bulbo Úmido", value="- °C")
            st.metric(label="Delta T", value="- °C")
            st.info("Condição: -")
            if img_grafico_base_original:
                st.image(img_grafico_base_original, caption="Gráfico de Referência", use_column_width=True)
            else:
                st.warning("Não foi possível carregar a imagem do gráfico de referência (após erro de cálculo).")
        elif t_w_calculada is not None:
            st.metric(label="Temperatura Bulbo Úmido", value=f"{t_w_calculada:.2f} °C")
            st.metric(label="Delta T", value=f"{resultado_delta_t:.2f} °C", delta_color="off")

            st.subheader("Interpretação do Delta T (Condições de Pulverização):")
            if resultado_delta_t < 2:
                st.warning("🔴 Delta T < 2°C: NÃO RECOMENDADO. Alto risco de deriva por escorrimento ou inversão térmica.")
            elif 2 <= resultado_delta_t <= 8:
                st.success(f"🟢 Delta T entre 2-8°C ({resultado_delta_t:.1f}°C): IDEAL. Boas condições de pulverização.")
            elif 8 < resultado_delta_t <= 10:
                 st.info(f"🟡 Delta T entre 8-10°C ({resultado_delta_t:.1f}°C): ATENÇÃO. Evaporação moderada, monitore.")
            else:
                st.error(f"🟠 Delta T > 10°C ({resultado_delta_t:.1f}°C): NÃO RECOMENDADO. Alto risco de deriva por evaporação excessiva das gotas.")

            if img_grafico_base_original:
                st.write("DEBUG: Entrando na lógica para sobrepor o alvo...") # DEBUG
                imagem_com_alvo = sobrepor_alvo_no_grafico(
                    img_grafico_base_original,
                    URL_ALVO_EMOJI,
                    temp_bulbo_seco_input,
                    umidade_relativa_input,
                    PARAMETROS_GRAFICO
                )
                if imagem_com_alvo:
                    st.write("DEBUG: Imagem com alvo gerada. Exibindo...") # DEBUG
                    st.image(imagem_com_alvo, caption=f"Ponto no Gráfico: Temp={temp_bulbo_seco_input}°C, UR={umidade_relativa_input}%", use_column_width=True)
                else:
                    st.error("DEBUG: Falha ao gerar imagem com alvo. `imagem_com_alvo` é None.") # DEBUG
                    st.write("DEBUG: Exibindo gráfico base original como fallback.") #DEBUG
                    st.image(img_grafico_base_original, caption="Gráfico de Referência (Falha ao plotar alvo)", use_column_width=True)

            else:
                st.warning("Não foi possível carregar a imagem base do gráfico para plotar o alvo (img_grafico_base_original is None).")
        else:
            st.error("Ocorreu um erro desconhecido no cálculo.")
            if img_grafico_base_original:
                st.image(img_grafico_base_original, caption="Gráfico de Referência (após erro desconhecido)", use_column_width=True)
    else:
        st.info("Ajuste os valores à esquerda e clique no botão para calcular e ver o ponto no gráfico.")
        st.metric(label="Temperatura Bulbo Úmido", value="- °C")
        st.metric(label="Delta T", value="- °C")
        st.info("Condição: -")
        if img_grafico_base_original:
            st.image(img_grafico_base_original, caption="Gráfico de Referência (Aguardando cálculo)", use_column_width=True)
        else:
            st.warning("Não foi possível carregar a imagem do gráfico de referência (estado inicial).")

st.markdown("---")
st.markdown("A **Temperatura de Bulbo Úmido ($T_w$)** é a menor temperatura para a qual o ar pode ser resfriado por evaporação de água nele, a pressão constante. A fórmula de Stull é uma aproximação empírica.")
st.markdown("O **Delta T ($\Delta T$)** é a diferença entre a Temperatura de Bulbo Seco ($T_{bs}$) e a Temperatura de Bulbo Úmido ($T_w$). É um indicador das condições de evaporação e da adequação para pulverização agrícola.")
st.latex(r''' \Delta T = T_{bs} - T_w ''')
