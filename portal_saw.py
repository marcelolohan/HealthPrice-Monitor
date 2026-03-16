from selenium import webdriver
from selenium.webdriver.common.by import By

from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import time
import os
import sys
import re
import json

from download_tracker import DownloadTracker

# ======================
# CONFIGURAÇÕES
# ======================

usuario     = os.environ.get("PORTAL_USUARIO", "")
senha       = os.environ.get("PORTAL_SENHA", "")
download_dir = os.environ.get("PORTAL_DOWNLOAD_DIR", "")

if not download_dir or not usuario or not senha:
    print("[ERRO] Credenciais nao configuradas. Execute via web app.")
    sys.exit(1)

os.makedirs(download_dir, exist_ok=True)

registro_file = os.path.join(download_dir, ".registro_downloads.json")

options = webdriver.ChromeOptions()

prefs = {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True
}

options.add_experimental_option("prefs", prefs)
options.add_argument("--headless=new")
options.add_argument("--disable-extensions")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")

print("[1] Iniciando ChromeDriver...", flush=True)
driver = webdriver.Chrome(options=options)   # Selenium Manager cuida do driver automaticamente
driver.set_page_load_timeout(30)
wait = WebDriverWait(driver, 30)
driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
    "behavior": "allow",
    "downloadPath": download_dir,
    "eventsEnabled": True,
})
print("[2] ChromeDriver iniciado.", flush=True)

# ======================
# REGISTRO PERSISTENTE
# ======================

def carregar_registro():
    if os.path.exists(registro_file):
        with open(registro_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def salvar_registro(registro):
    with open(registro_file, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2)

def obter_chave(icone):
    try:
        link = icone.find_element(By.XPATH, "./ancestor::a[1]")
        href = link.get_attribute("href") or ""
        onclick = link.get_attribute("onclick") or ""
        if href and href not in ("#", "javascript:void(0)", "javascript:;"):
            return href.strip()
        if onclick:
            return onclick.strip()
    except Exception:
        pass
    try:
        row = icone.find_element(By.XPATH, "./ancestor::tr[1]")
        texto = row.text.strip()
        if texto:
            return texto
    except Exception:
        pass
    return None

def nome_base_arquivo(nome):
    nome_sem_ext, ext = os.path.splitext(nome)
    nome_limpo = re.sub(r'\s*\(\d+\)$', '', nome_sem_ext).strip()
    return nome_limpo

def ja_existe_na_pasta(pasta, nome_baixado):
    base = nome_base_arquivo(nome_baixado)
    for f in os.listdir(pasta):
        if f == nome_baixado:
            continue
        if nome_base_arquivo(f).lower() == base.lower():
            return True
    return False

# ======================
# ABRIR SITE
# ======================

print("[3] Abrindo site...", flush=True)
driver.get("https://sawb.trixti.com.br/saw/Logar.do?method=abrirSAW")
print("[4] Site aberto. Aguardando campo login...", flush=True)

# ======================
# LOGIN
# ======================

wait.until(EC.presence_of_element_located((By.ID, "login"))).send_keys(usuario)
print("[5] Usuario preenchido.", flush=True)
driver.find_element(By.ID, "password").send_keys(senha)

driver.find_element(By.ID, "submitForm").click()
print("[6] Formulario enviado. Aguardando redirecionamento...", flush=True)

login_url = driver.current_url
try:
    # O SAW pode não mudar URL após login — verifica URL OU aparecimento de conteúdo autenticado
    WebDriverWait(driver, 25).until(lambda d:
        d.current_url != login_url or
        "Local de Atendimento" in d.find_element(By.TAG_NAME, "body").text or
        "ManterDownload" in d.current_url or
        "abrirMenu" in d.current_url or
        "Pesquisar" in d.find_element(By.TAG_NAME, "body").text
    )
    # Verifica se ainda está na tela de erro de login
    body_now = driver.find_element(By.TAG_NAME, "body").text.lower()
    error_kws = ["senha inv", "usuario inv", "login inv", "acesso neg", "credenciais inv", "nao autorizado"]
    if any(kw in body_now for kw in error_kws):
        print(f"[LOGIN_FAILED] Credenciais invalidas.", flush=True)
        driver.quit()
        sys.exit(2)
    print("Login realizado", flush=True)
except Exception:
    body_text = "sem detalhes"
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text[:200]
        # Se o body já mostra conteúdo autenticado, o login foi bem-sucedido
        if "Local de Atendimento" in body_text or "Pesquisar" in body_text:
            print("Login realizado (conteudo autenticado detectado)", flush=True)
        else:
            print(f"[LOGIN_FAILED] Credenciais invalidas ou portal nao redirecionou. Detalhes: {body_text}", flush=True)
            driver.quit()
            sys.exit(2)
    except Exception:
        print(f"[LOGIN_FAILED] Sem resposta do portal.", flush=True)
        driver.quit()
        sys.exit(2)

# ======================
# ABRIR DOWNLOADS DIRETO
# ======================

print("[7] Abrindo tela de downloads...", flush=True)
driver.get("https://sawb.trixti.com.br/saw/ManterDownload.do?method=abrirTelaDeListagemDeDownloadsPorTipoDeUsuario")

print("Tela Downloads aberta", flush=True)

# ======================
# FILTROS
# ======================

hoje = datetime.today()
inicio = hoje - timedelta(days=60)

data_inicial = inicio.strftime("%d/%m/%Y")
data_final = hoje.strftime("%d/%m/%Y")

def abrir_lista_downloads():
    driver.get("https://sawb.trixti.com.br/saw/ManterDownload.do?method=abrirTelaDeListagemDeDownloadsPorTipoDeUsuario")
    select_classificacao = Select(
        wait.until(
            EC.presence_of_element_located(
                (By.NAME, "manterDownloadDTO.filtroDePesquisaDeDownloadDTO.classificacaoDTO.chave")
            )
        )
    )
    select_classificacao.select_by_index(1)

    campo_inicio = wait.until(EC.presence_of_element_located((By.ID, "dataInicial")))
    campo_inicio.clear()
    campo_inicio.send_keys(data_inicial)

    campo_fim = driver.find_element(By.ID, "dataFinal")
    campo_fim.clear()
    campo_fim.send_keys(data_final)

    driver.find_element(By.NAME, "btnPesquisar").click()

    return wait.until(
        EC.presence_of_all_elements_located((By.XPATH, "//img[contains(@src,'download')]"))
    )

print("[8] Aguardando select de classificacao...", flush=True)
print("[9] Filtros preenchidos. Pesquisando...", flush=True)
print(f"Periodo: {data_inicial} ate {data_final}", flush=True)

# ======================
# PESQUISAR
# ======================

icones = abrir_lista_downloads()

print("Pesquisa realizada", flush=True)

# ======================
# LOCALIZAR ÍCONES DE DOWNLOAD
# ======================

print("[10] Aguardando icones de download...", flush=True)

total = len(icones)
print(f"{total} arquivos encontrados", flush=True)

# ======================
# FUNÇÃO: AGUARDAR DOWNLOAD CONCLUIR
# ======================

def aguardar_download(pasta, arquivos_antes, timeout=300):
    """
    Aguarda novo arquivo aparecer na pasta.
    - Monitora crescimento do .crdownload para detectar download ativo
    - Timeout global de 300s; mas se o arquivo parar de crescer por 30s, desiste
    """
    time.sleep(1.5)
    fim = time.time() + timeout
    ultimo_tamanho = {}
    ultimo_crescimento = time.time()

    while time.time() < fim:
        try:
            arquivos_agora = set(os.listdir(pasta))
        except Exception:
            time.sleep(1)
            continue

        novos = arquivos_agora - arquivos_antes
        em_progresso = [f for f in novos if f.endswith(".crdownload") or f.endswith(".tmp")]
        concluidos   = [f for f in novos if not f.endswith(".crdownload") and not f.endswith(".tmp")]

        # Arquivo concluído
        if concluidos and not em_progresso:
            return concluidos[0]

        # Verifica se arquivo em progresso está crescendo
        if em_progresso:
            fp = os.path.join(pasta, em_progresso[0])
            try:
                tamanho_atual = os.path.getsize(fp)
            except Exception:
                tamanho_atual = 0

            decorrido = timeout - (fim - time.time())
            kb = tamanho_atual / 1024
            print(f"  [DOWN] Baixando {em_progresso[0]} — {kb:.0f} KB ({decorrido:.0f}s)", flush=True)

            if em_progresso[0] in ultimo_tamanho:
                if tamanho_atual > ultimo_tamanho[em_progresso[0]]:
                    ultimo_crescimento = time.time()  # arquivo cresceu
                elif time.time() - ultimo_crescimento > 30:
                    print(f"  [DOWN] Arquivo parou de crescer por 30s — possivel erro de rede.", flush=True)
                    break
            ultimo_tamanho[em_progresso[0]] = tamanho_atual

        time.sleep(1.5)

    # timeout ou arquivo parou — reportar estado
    try:
        arqs = list(os.listdir(pasta))
        print(f"  [DOWN] Timeout. Arquivos em pasta: {arqs[:10]}", flush=True)
        # Se .crdownload existe, pode ser que ainda esteja baixando em background
        crdownloads = [f for f in arqs if f.endswith(".crdownload")]
        if crdownloads:
            print(f"  [DOWN] Arquivo parcial detectado: {crdownloads[0]} — pode concluir em background.", flush=True)
    except Exception:
        pass
    return None

# ======================
# BAIXAR ARQUIVOS
# ======================
# DownloadTracker cuida de toda deduplicação por nome/hash

tracker = DownloadTracker(download_dir)
tracker.limpar_invalidos()  # remove entradas de arquivos apagados

for i in range(total):
    print(f"\n--- Download {i+1}/{total} ---", flush=True)
    try:
        icones = wait.until(
            EC.presence_of_all_elements_located((By.XPATH, "//img[contains(@src,'download')]"))
        )
        print(f"  [DEBUG] {len(icones)} icones de download encontrados na pagina", flush=True)

        if i >= len(icones):
            print(f"  [ERRO] Indice {i} fora do range ({len(icones)} icones). Pulando.", flush=True)
            continue

        icone = icones[i]
        chave = obter_chave(icone)
        print(f"  [DEBUG] Icone src: {icone.get_attribute('src')}", flush=True)
        print(f"  [DEBUG] Chave do arquivo: {chave}", flush=True)

        # Verifica deduplicação pelo tracker (nome normalizado + chave portal)
        # O nome ainda não é conhecido antes do download; verificamos pela chave e depois pelo arquivo
        if chave and tracker.ja_baixado("", chave_portal=chave):
            print(f"  [IGNORAR] Chave ja registrada: {chave}", flush=True)
            continue

        arquivos_antes = set(os.listdir(download_dir))
        print(f"  [DEBUG] Arquivos antes do click: {len(arquivos_antes)}", flush=True)

        # Scroll e click no ícone de download
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", icone)
        time.sleep(0.5)
        wait.until(EC.element_to_be_clickable(icone))

        # Verifica se há nova janela/aba após o click
        janelas_antes = set(driver.window_handles)
        icone.click()
        time.sleep(1.5)

        janelas_depois = set(driver.window_handles)
        novas_janelas = janelas_depois - janelas_antes
        if novas_janelas:
            print(f"  [DEBUG] Nova aba/janela aberta: {novas_janelas}", flush=True)
            nova = list(novas_janelas)[0]
            driver.switch_to.window(nova)
            time.sleep(2)
            print(f"  [DEBUG] URL nova aba: {driver.current_url}", flush=True)
            driver.close()
            driver.switch_to.window(janela_principal)

        print(f"  [DOWN] Click realizado. Aguardando arquivo em: {download_dir}", flush=True)
        nome_baixado = aguardar_download(download_dir, arquivos_antes)  # usa timeout=300s

        if nome_baixado:
            if tracker.ja_baixado(nome_baixado):
                try:
                    os.remove(os.path.join(download_dir, nome_baixado))
                except Exception:
                    pass
                print(f"  [IGNORAR] Arquivo duplicado removido: {nome_baixado}", flush=True)
            else:
                print(f"Download {i+1}/{total} concluido: {nome_baixado}", flush=True)
                tracker.registrar(nome_baixado, chave_portal=chave)
        else:
            # Diagnóstico extra quando falha
            print(f"Download {i+1}/{total} demorou mais que o esperado", flush=True)
            try:
                print(f"  [DEBUG] URL atual: {driver.current_url}", flush=True)
                print(f"  [DEBUG] Titulo: {driver.title}", flush=True)
                # Verifica se o arquivo está no download padrão do Chrome
                default_dl = os.path.join(os.path.expanduser("~"), "Downloads")
                arqs_default = set(os.listdir(default_dl)) if os.path.isdir(default_dl) else set()
                novos_default = arqs_default - set()  # comparação básica
                recentes_default = [f for f in arqs_default if ".crdownload" not in f and ".tmp" not in f
                                    and os.path.getmtime(os.path.join(default_dl, f)) > time.time() - 300]
                if recentes_default:
                    print(f"  [DEBUG] Arquivos recentes na pasta Downloads padrao: {recentes_default[:5]}", flush=True)
            except Exception as dbg_err:
                print(f"  [DEBUG] Erro no diagnostico: {dbg_err}", flush=True)

    except Exception as e:
        import traceback
        print(f"Erro no download {i+1}: {e}", flush=True)
        print(traceback.format_exc(), flush=True)

print("\nDownloads finalizados", flush=True)

# Só pede ENTER se rodando interativamente (não via subprocess)
if sys.stdin.isatty():
    input("Pressione ENTER para fechar")

driver.quit()
