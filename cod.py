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
    valor_clamped = max(de_min, min(valor, de_max)) # Garante que o valor esteja dentro da faixa de dados
    # Se a faixa de dados for zero (de_min == de_max), retorna o início da faixa de destino para evitar divisão por zero
    if (de_max - de_min) == 0:
        return para_min
    return (valor_clamped - de_min) * (para_max - para_min) / (de_max - de_min) + para_min

def sobrepor_alvo_no_grafico(img_grafico_base, img_alvo_url, temp_para_plotar, umidade_para_plotar, params_grafico):
    if img_grafico_base is None:
        return None

    img_alvo = carregar_imagem_de_url(img_alvo_url)
    if img_alvo is None:
        st.warning("Não foi possível carregar a imagem do alvo. Exibindo gráfico base.")
        return img_grafico_base.copy()

    tamanho_alvo = (40, 40) # Ajuste o tamanho do alvo conforme necessário
    try:
        img_alvo = img_alvo.resize(tamanho_alvo, Image.Resampling.LANCZOS)
    except Exception as e:
        st.error(f"Erro ao redimensionar imagem do alvo: {e}")
        return img_grafico_base.copy()

    # Calcular coordenadas X e Y para o alvo
    # Eixo X do GRÁFICO é Temperatura
    coord_x = mapear_valor(
        temp_para_plotar, # Valor da temperatura de bulbo seco
        params_grafico["temp_min_dado_eixo_x"], params_grafico["temp_max_dado_eixo_x"],
        params_grafico["temp_pixel_min_eixo_x"], params_grafico["temp_pixel_max_eixo_x"]
    )
    # Eixo Y do GRÁFICO é Umidade Relativa
    coord_y = mapear_valor(
        umidade_para_plotar, # Valor da umidade relativa
        params_grafico["umidade_min_dado_eixo_y"], params_grafico["umidade_max_dado_eixo_y"],
        params_grafico["umidade_pixel_para_min_dado_eixo_y"], params_grafico["umidade_pixel_para_max_dado_eixo_y"]
    )

    pos_x_paste = int(coord_x - img_alvo.width / 2)
    pos_y_paste = int(coord_y - img_alvo.height / 2)

    img_com_alvo = img_grafico_base.copy()
    if img_alvo.mode == 'RGBA':
        img_com_alvo.paste(img_alvo, (pos_x_paste, pos_y_paste), img_alvo)
    else:
        img_com_alvo.paste(img_alvo, (pos_x_paste, pos_y_paste))

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
    if not (0 <= rh <= 100): # Validação da umidade relativa de entrada
        # No entanto, para plotar, usaremos os limites do eixo do gráfico se a UR estiver fora de 10-100%
        # Mas a função de cálculo ainda deve validar a entrada bruta.
        return "Erro: A umidade relativa (entrada) deve estar entre 0 e 100%.", None
    if t_bs < -50 or t_bs > 60: # Validação da temperatura de entrada
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
st.caption("Baseada na fórmula de Stull para Temperatura de Bulbo Úmido. O ponto no gráfico indica a condição de entrada.")

# --- Configuração do Gráfico e Alvo ---
# Use a URL da imagem do gráfico que você está utilizando
URL_GRAFICO_BASE = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg" # Ou a URL correta da sua imagem de gráfico
URL_ALVO_EMOJI = "https://estudioweb.com.br/wp-content/uploads/2023/02/Emoji-Alvo-png.png"

# PARAMETROS DO GRÁFICO BASEADOS NAS SUAS INFORMAÇÕES:
PARAMETROS_GRAFICO = {
    # Eixo X do Gráfico (Horizontal) = Temperatura (°C)
    "temp_min_dado_eixo_x": 0.0,    # Valor mínimo de Temperatura no eixo X do GRÁFICO
    "temp_max_dado_eixo_x": 50.0,   # Valor máximo de Temperatura no eixo X do GRÁFICO
    "temp_pixel_min_eixo_x": 443,   # Coordenada X em PIXEL na imagem para temp_min_dado_eixo_x
    "temp_pixel_max_eixo_x": 1965,  # Coordenada X em PIXEL na imagem para temp_max_dado_eixo_x

    # Eixo Y do Gráfico (Vertical) = Umidade Relativa (%)
    "umidade_min_dado_eixo_y": 10.0,  # Valor mínimo de Umidade Relativa no eixo Y do GRÁFICO
    "umidade_max_dado_eixo_y": 100.0, # Valor máximo de Umidade Relativa no eixo Y do GRÁFICO
    "umidade_pixel_para_min_dado_eixo_y": 1450, # Coordenada Y em PIXEL para umidade_min_dado_eixo_y (10% UR)
    "umidade_pixel_para_max_dado_eixo_y": 242,  # Coordenada Y em PIXEL para umidade_max_dado_eixo_y (100% UR)
}

@st.cache_data # Cache para a imagem base do gráfico
def carregar_grafico_base_cache(url):
    return carregar_imagem_de_url(url)

img_grafico_base_original = carregar_grafico_base_cache(URL_GRAFICO_BASE)

# Layout com colunas
col_entrada, col_resultados = st.columns(2)

with col_entrada:
    st.header("Entrada de Dados")
    temp_bulbo_seco_input = st.number_input(
        "Temperatura de Bulbo Seco (°C):",
        min_value=PARAMETROS_GRAFICO["temp_min_dado_eixo_x"], # Usar limites do gráfico como guia
        max_value=PARAMETROS_GRAFICO["temp_max_dado_eixo_x"],
        value=25.0, step=0.1, format="%.1f",
        help=f"Valores típicos entre {PARAMETROS_GRAFICO['temp_min_dado_eixo_x']}°C e {PARAMETROS_GRAFICO['temp_max_dado_eixo_x']}°C para este gráfico."
    )
    umidade_relativa_input = st.number_input(
        "Umidade Relativa (%):",
        min_value=PARAMETROS_GRAFICO["umidade_min_dado_eixo_y"], # Usar limites do gráfico como guia
        max_value=PARAMETROS_GRAFICO["umidade_max_dado_eixo_y"],
        value=60.0, step=0.1, format="%.1f",
        help=f"Valores típicos entre {PARAMETROS_GRAFICO['umidade_min_dado_eixo_y']}% e {PARAMETROS_GRAFICO['umidade_max_dado_eixo_y']}% para este gráfico."
    )
    calcular_btn = st.button("Calcular Delta T e Mostrar no Gráfico", type="primary")

with col_resultados:
    st.header("Resultados e Gráfico")
    if calcular_btn:
        # Para o cálculo do Delta T, usar os inputs diretos, pois a fórmula de Stull pode aceitar UR 0-100
        # A função calcular_delta_t já valida os ranges de entrada para o cálculo em si.
        resultado_delta_t, t_w_calculada = calcular_delta_t(temp_bulbo_seco_input, umidade_relativa_input)

        if isinstance(resultado_delta_t, str): # Erro no cálculo
            st.error(resultado_delta_t)
            st.metric(label="Temperatura Bulbo Úmido", value="- °C")
            st.metric(label="Delta T", value="- °C")
            st.info("Condição: -")
            if img_grafico_base_original:
                st.image(img_grafico_base_original, caption="Gráfico de Referência", use_column_width=True)
            else:
                st.warning("Não foi possível carregar a imagem do gráfico de referência.")
        elif t_w_calculada is not None: # Cálculo bem-sucedido
            st.metric(label="Temperatura Bulbo Úmido", value=f"{t_w_calculada:.2f} °C")
            st.metric(label="Delta T", value=f"{resultado_delta_t:.2f} °C", delta_color="off")

            st.subheader("Interpretação do Delta T (Condições de Pulverização):")
            if resultado_delta_t < 2:
                st.warning("🔴 Delta T < 2°C: NÃO RECOMENDADO. Alto risco de deriva por escorrimento ou inversão térmica.")
            elif 2 <= resultado_delta_t <= 8:
                st.success(f"🟢 Delta T entre 2-8°C ({resultado_delta_t:.1f}°C): IDEAL. Boas condições de pulverização.")
            elif 8 < resultado_delta_t <= 10:
                 st.info(f"🟡 Delta T entre 8-10°C ({resultado_delta_t:.1f}°C): ATENÇÃO. Evaporação moderada, monitore.")
            else: # resultado_delta_t > 10
                st.error(f"🟠 Delta T > 10°C ({resultado_delta_t:.1f}°C): NÃO RECOMENDADO. Alto risco de deriva por evaporação excessiva das gotas.")

            if img_grafico_base_original:
                # Para plotar, usamos os inputs, a função mapear_valor fará o clamp para os limites do gráfico.
                imagem_com_alvo = sobrepor_alvo_no_grafico(
                    img_grafico_base_original,
                    URL_ALVO_EMOJI,
                    temp_bulbo_seco_input, # Valor de temperatura para o eixo X do gráfico
                    umidade_relativa_input, # Valor de umidade para o eixo Y do gráfico
                    PARAMETROS_GRAFICO
                )
                if imagem_com_alvo:
                    st.image(imagem_com_alvo, caption=f"Ponto no Gráfico: Temp={temp_bulbo_seco_input}°C, UR={umidade_relativa_input}%", use_column_width=True)
            else:
                st.warning("Não foi possível carregar a imagem base do gráfico para plotar o alvo.")
        else:
            st.error("Ocorreu um erro desconhecido no cálculo.")
            if img_grafico_base_original:
                st.image(img_grafico_base_original, caption="Gráfico de Referência", use_column_width=True)
    else:
        st.info("Ajuste os valores à esquerda e clique no botão para calcular e ver o ponto no gráfico.")
        st.metric(label="Temperatura Bulbo Úmido", value="- °C")
        st.metric(label="Delta T", value="- °C")
        st.info("Condição: -")
        if img_grafico_base_original:
            st.image(img_grafico_base_original, caption="Gráfico de Referência (Aguardando cálculo para plotar o ponto)", use_column_width=True)
        else:
            st.warning("Não foi possível carregar a imagem do gráfico de referência.")

st.markdown("---")
st.markdown("A **Temperatura de Bulbo Úmido ($T_w$)** é a menor temperatura para a qual o ar pode ser resfriado por evaporação de água nele, a pressão constante. A fórmula de Stull é uma aproximação empírica.")
st.markdown("O **Delta T ($\Delta T$)** é a diferença entre a Temperatura de Bulbo Seco ($T_{bs}$) e a Temperatura de Bulbo Úmido ($T_w$). É um indicador das condições de evaporação e da adequação para pulverização agrícola.")
st.latex(r''' \Delta T = T_{bs} - T_w ''')
