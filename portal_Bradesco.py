import os
import sys
import glob
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

DOWNLOAD_DIR = os.environ.get("PORTAL_DOWNLOAD_DIR", "")
CNPJ         = os.environ.get("PORTAL_CNPJ", "")
CPF          = os.environ.get("PORTAL_CPF", "")
SENHA        = os.environ.get("PORTAL_SENHA", "")

if not DOWNLOAD_DIR or not CNPJ or not CPF or not SENHA:
    print("[ERRO] Credenciais nao configuradas. Execute via web app.")
    sys.exit(1)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def ja_existe(extensoes):
    for ext in extensoes:
        if glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}")):
            return True
    return False

def aguardar_download(extensoes, timeout=60):
    inicio = time.time()
    while time.time() - inicio < timeout:
        time.sleep(2)
        em_andamento = glob.glob(os.path.join(DOWNLOAD_DIR, "*.crdownload")) + glob.glob(os.path.join(DOWNLOAD_DIR, "*.tmp"))
        for ext in extensoes:
            arquivos = glob.glob(os.path.join(DOWNLOAD_DIR, f"*{ext}"))
            if arquivos and not em_andamento:
                return max(arquivos, key=os.path.getmtime)
    return None

def aceitar_termo_e_baixar(janela_principal):
    WebDriverWait(driver, 20).until(lambda d: len(d.window_handles) > 1)
    janela_termo = [w for w in driver.window_handles if w != janela_principal][-1]
    driver.switch_to.window(janela_termo)
    print("  Janela do termo aberta:", driver.current_url)
    time.sleep(2)
    checkbox = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@type='checkbox']")))
    driver.execute_script("arguments[0].click()", checkbox)
    print("  Checkbox marcado!")
    time.sleep(1)
    ok_btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//input[@value='OK'] | //button[contains(text(),'OK')]")))
    driver.execute_script("arguments[0].click()", ok_btn)
    print("  Clicou em OK!")
    time.sleep(2)
    driver.switch_to.window(janela_principal)

chrome_options = Options()
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "plugins.always_open_pdf_externally": True
})
chrome_options.add_argument("--window-size=1024,768")
chrome_options.add_argument("--window-position=100,100")

print("[AVISO] Bradesco requer resolucao de captcha manual.")
print("[AVISO] Uma janela do navegador sera aberta. Resolva o captcha e aguarde.")
driver = webdriver.Chrome(options=chrome_options)
janela_principal = driver.current_window_handle
driver.get("https://wwws.bradescosaude.com.br/PCBS-GerenciadorPortal/td/loginReferenciado.do")
wait = WebDriverWait(driver, 30)

try:
    wait.until(EC.presence_of_element_located((By.ID, "adopt-accept-all-button")))
    driver.execute_script("document.getElementById('adopt-accept-all-button').click()")
    time.sleep(1)
except:
    pass

driver.execute_script("document.getElementById('pj').click()")
wait.until(EC.visibility_of_element_located((By.ID, "cnpjRef"))).send_keys(CNPJ)
wait.until(EC.visibility_of_element_located((By.ID, "cpfRefPJ"))).send_keys(CPF)
wait.until(EC.visibility_of_element_located((By.ID, "senhaRef"))).send_keys(SENHA)
wait.until(EC.element_to_be_clickable((By.ID, "btLoginReferenciado"))).click()

print("Resolva o captcha no navegador. Aguardando login...")
url_login = driver.current_url
try:
    WebDriverWait(driver, 120).until(lambda d: d.current_url != url_login)
except Exception:
    print("[LOGIN_FAILED] Timeout aguardando login — captcha nao resolvido ou credenciais invalidas.", flush=True)
    driver.quit()
    sys.exit(2)

try:
    # Só considera erro se o elemento está visível E tem texto não-vazio
    error_els = driver.find_elements(By.XPATH, "//*[contains(@class,'erro') or contains(@class,'error') or contains(@id,'erro')]")
    error_real = [e for e in error_els if e.is_displayed() and e.text.strip()]
    if error_real:
        msg = error_real[0].text.strip()
        print(f"[LOGIN_FAILED] Erro no portal: {msg}", flush=True)
        driver.quit()
        sys.exit(2)
    # Verifica também se a URL ainda é a de login (algo falhou)
    if "loginReferenciado" in driver.current_url or "login" in driver.current_url.lower():
        body_snip = driver.find_element(By.TAG_NAME, "body").text[:300]
        print(f"[LOGIN_FAILED] URL ainda e login apos captcha. Body: {body_snip}", flush=True)
        driver.quit()
        sys.exit(2)
except Exception:
    pass

janela_principal = driver.current_window_handle
print("Login realizado com sucesso! URL atual:", driver.current_url, flush=True)
time.sleep(3)

# ── Esconde banners/iframes de feedback ──────────────────────────────────────
try:
    driver.execute_script("""
        var frames = document.querySelectorAll('iframe[id^="kampyle"]');
        frames.forEach(function(f){ f.style.display='none'; });
    """)
    time.sleep(1)
except Exception:
    pass

# ── Abre menu hamburguer ──────────────────────────────────────────────────────
print("Abrindo menu hamburguer...", flush=True)
try:
    nav_toggle = driver.find_element(By.CSS_SELECTOR, ".bs-header__nav-toggle")
    driver.execute_script("arguments[0].click()", nav_toggle)
except Exception:
    try:
        driver.execute_script("document.querySelector('.bs-header__nav-toggle').click()")
    except Exception as e:
        print(f"[AVISO] Nao encontrou .bs-header__nav-toggle: {e}", flush=True)
time.sleep(2)
print("Menu hamburguer aberto!", flush=True)

# ── Localiza link TUSS/TISS ──────────────────────────────────────────────────
print("Localizando menu TUSS/TISS...", flush=True)
tuss_link = None
try:
    tuss_link = driver.find_element(
        By.XPATH,
        "//ul[@id='ul-menu-hamb'][.//li[@id='menu-li-TUSS']]/preceding-sibling::a[@id='titulo-menu-hamb']"
    )
except Exception:
    pass

if tuss_link is None:
    # fallback: busca por texto
    try:
        tuss_link = driver.find_element(
            By.XPATH,
            "//a[contains(translate(.,'tuss','TUSS'),'TUSS') or contains(translate(.,'tiss','TISS'),'TISS')]"
        )
    except Exception:
        pass

if tuss_link is None:
    try:
        tuss_link = driver.find_element(By.XPATH, "//li[@id='menu-li-TUSS']/parent::ul/preceding-sibling::a")
    except Exception:
        pass

if tuss_link is None:
    print("[ERRO] Nao foi possivel localizar o menu TUSS/TISS. O portal pode ter mudado sua estrutura.", flush=True)
    print(f"[DEBUG] URL atual: {driver.current_url}", flush=True)
    print(f"[DEBUG] Titulo da pagina: {driver.title}", flush=True)
    try:
        print(f"[DEBUG] Links visiveis no menu: {[el.text for el in driver.find_elements(By.CSS_SELECTOR, '#ul-menu-hamb a')][:10]}", flush=True)
    except Exception:
        pass
    driver.quit()
    sys.exit(1)

driver.execute_script("arguments[0].click()", tuss_link)
print("Clicou em TUSS/TISS!", flush=True)
time.sleep(2)

# ── Localiza submenu THSM ────────────────────────────────────────────────────
print("Localizando submenu Tabela de Honorarios e Servicos Medicos (THSM)...", flush=True)
thsm = None
try:
    thsm = wait.until(EC.element_to_be_clickable((By.ID, "submenu-2013012214")))
except Exception:
    pass

if thsm is None:
    # fallback: busca por texto
    try:
        thsm = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//*[contains(text(),'Honorarios') or contains(text(),'Honorários') or contains(text(),'THSM')]"
        )))
    except Exception:
        pass

if thsm is None:
    print("[ERRO] Nao foi possivel localizar o submenu THSM.", flush=True)
    try:
        submenus = driver.find_elements(By.CSS_SELECTOR, "[id^='submenu-']")
        print(f"[DEBUG] Submenus encontrados: {[(el.get_attribute('id'), el.text[:40]) for el in submenus[:15]]}", flush=True)
    except Exception:
        pass
    driver.quit()
    sys.exit(1)

driver.execute_script("arguments[0].click()", thsm)
print("Clicou em THSM!", flush=True)

# ── Aguarda iframe do popup ───────────────────────────────────────────────────
print("Aguardando iframePopUp...", flush=True)
try:
    wait.until(EC.presence_of_element_located((By.ID, "iframePopUp")))
except Exception:
    # tenta outros nomes possíveis de iframe
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[id*='Popup'], iframe[id*='popup'], iframe[name*='popup']")))
    except Exception as e:
        print(f"[ERRO] iframePopUp nao encontrado: {e}", flush=True)
        print(f"[DEBUG] iframes presentes: {[el.get_attribute('id') or el.get_attribute('name') or '?' for el in driver.find_elements(By.TAG_NAME, 'iframe')]}", flush=True)
        driver.quit()
        sys.exit(1)
time.sleep(4)
print("iframePopUp encontrado!", flush=True)

if ja_existe([".pdf"]):
    print("[PDF] Arquivo PDF ja existe na pasta. Download ignorado.")
else:
    print("[PDF] Iniciando download...")
    driver.switch_to.frame("iframePopUp")
    tabela_pdf = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(),'Tabela PDF')]")))
    driver.execute_script("arguments[0].click()", tabela_pdf)
    driver.switch_to.default_content()
    aceitar_termo_e_baixar(janela_principal)
    arquivo = aguardar_download([".pdf"])
    if arquivo:
        print(f"[PDF] Download concluido: {arquivo}")
    else:
        print("[PDF] AVISO: Download nao detectado em 60 segundos.")

if ja_existe([".xls", ".xlsx"]):
    print("[Excel] Arquivo Excel ja existe na pasta. Download ignorado.")
else:
    print("[Excel] Iniciando download...")
    driver.switch_to.frame("iframePopUp")
    tabela_excel = wait.until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(),'Tabela Excel')]")))
    driver.execute_script("arguments[0].click()", tabela_excel)
    driver.switch_to.default_content()
    aceitar_termo_e_baixar(janela_principal)
    arquivo = aguardar_download([".xls", ".xlsx"])
    if arquivo:
        print(f"[Excel] Download concluido: {arquivo}")
    else:
        print("[Excel] AVISO: Download nao detectado em 60 segundos.")

print("\nAutomacao finalizada!")
driver.quit()
