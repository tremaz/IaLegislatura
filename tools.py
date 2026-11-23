import base64
import io
from pathlib import Path
from tkinter import Tk, filedialog

from groq import Groq
from PIL import Image

leis = Path("FontesLegais.txt").read_text(encoding="utf-8")

GROQ_API_KEY = "pegar chave no groq"

EXTENSOES = "*.png *.jpg *.jpeg *.bmp *.gif *.webp"

ARQUIVO_SAIDA = Path(__file__).parent / "AnaliseDeImagem.txt"

MODELO_VISAO = "qwen/qwen3.8-27b"
VISAO_REASONING_EFFORT = "none" 

# Modelo que redige o texto final (só texto)
MODELO_ANALISE = "openai/gpt-oss-120b"
ANALISE_REASONING_EFFORT = "medium"   # "low", "medium" ou "high"

MAX_IMAGENS_POR_REQUISICAO = 3   # limite da Groq para o modelo de visão
LADO_MAX_PX = 1568               # reduz imagens grandes antes de enviar

PROMPT_PADRAO = (
    "Você é um urbanista sênior com experiência em planejamento urbano, legislação urbanística (plano diretor, lei de uso e ocupação do solo, código de obras e parcelamento do solo), licenciamento e análise de projetos, e sua tarefa é analisar tecnicamente 3 documentos anexados (imagens, plantas, mapas, quadros, tabelas ou páginas escaneadas) e produzir uma descrição tão completa que uma pessoa sem acesso a eles compreenda seu conteúdo, sua estrutura e suas conclusões; para cada documento, comece identificando tipo, título, órgão emissor ou responsável técnico, data, revisão, escala, folha, município e demais dados do carimbo ou legenda, depois interprete tecnicamente a imagem descrevendo o que é visível, como desenhos, hachuras, cores, simbologia, norte, cotas, curvas de nível, limites de lote, sistema viário, áreas verdes, edificações e recuos, sem se limitar a transcrever texto e explicitando localização, posição e relação espacial dos elementos, já que o leitor não verá os documentos; em seguida, reproduza fielmente todas as tabelas no formato PERGUNTA e RESPOSTA, em que a resposta é SIM (atende, está presente ou conforme), NÃO (não atende, ausente ou em desconformidade), INSUFICIENTE (informação parcial ou inadequada para concluir) ou N.A. (não se aplica ao caso), preservando a numeração e as observações do documento; depois faça a leitura do urbanista, explicando o que as respostas indicam sobre a conformidade, destacando os itens críticos marcados como NÃO ou INSUFICIENTE e seu impacto urbanístico, e verificando se as justificativas dos itens N.A. são coerentes; ao final, produza uma análise integrada dos 3 documentos contendo um resumo quantitativo de respostas por documento, a identificação de concordâncias e contradições entre eles (por exemplo, divergência de taxa de ocupação entre o quadro de parâmetros e a planta), a lista de pendências e riscos agrupados por tema (uso do solo, parâmetros edilícios, sistema viário, infraestrutura, meio ambiente, acessibilidade, patrimônio) com a ação corretiva sugerida, um parecer técnico conclusivo indicando conformidade, conformidade com ressalvas ou não conformidade, e um resumo narrativo autônomo de um a dois parágrafos que permita a alguém sem acesso aos documentos entender o caso analisado, sua localização, o que foi verificado, os principais resultados e o que falta resolver; não invente dados, indicando como ilegível o que não puder ser lido e como não visível no documento o que estiver cortado ou ausente, transcreva valores numéricos exatamente como aparecem com suas unidades, sinalize como inferência qualquer dedução que não esteja escrita, use terminologia urbanística correta (coeficiente de aproveitamento, taxa de ocupação, taxa de permeabilidade, gabarito, recuos, afastamentos, testada, ZEIS, APP, faixa non aedificandi), cite legislação apenas se constar nos documentos ou no contexto fornecido, indicando base legal não informada quando necessário, e mantenha um tom técnico, objetivo e impessoal em português do Brasil."
)

client = Groq(api_key=GROQ_API_KEY)


def selecionar_imagens(titulo: str = "Selecione as imagens") -> dict:
    """Abre uma janela para o usuário escolher uma ou várias imagens."""
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    caminhos = filedialog.askopenfilenames(
        title=titulo, filetypes=[("Imagens", EXTENSOES)]
    )
    root.destroy()

    if not caminhos:
        return {"sucesso": False, "mensagem": "Nenhuma imagem selecionada.", "imagens": []}

    imagens = []
    for caminho in caminhos:
        try:
            with Image.open(caminho) as img:
                imagens.append({
                    "caminho": caminho,
                    "formato": img.format,
                    "largura": img.width,
                    "altura": img.height,
                })
        except Exception as e:
            imagens.append({"caminho": caminho, "erro": str(e)})

    return {"sucesso": True, "total": len(imagens), "imagens": imagens}


def _imagem_para_data_url(caminho: str) -> str:
    """Redimensiona (se preciso), converte para JPEG e devolve como data URL base64."""
    with Image.open(caminho) as img:
        img = img.convert("RGB")  # remove transparência/paleta, JPEG exige RGB
        img.thumbnail((LADO_MAX_PX, LADO_MAX_PX))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def _descrever_com_visao(caminhos: list[str]) -> str:
    """Etapa 1: o modelo de visão descreve as imagens do lote."""
    instrucao = (
        "Você está lendo documentos. Para cada imagem, na ordem enviada "
        "(Documento 1, Documento 2, ...), informe: tipo de documento, emissor, "
        "destinatário, número e data; depois transcreva de forma compacta apenas o "
        "conteúdo essencial: títulos, cláusulas ou itens principais, tabelas (colunas "
        "e valores), valores, unidades, prazos, nomes, códigos e carimbos. "
        "Copie números e códigos exatamente como estão. Use [ilegível] ou [incerto] "
        "quando necessário. Não interprete nem resuma além do necessário. "
        "Seja objetivo: sua resposta total, somando todos os documentos, deve ter no "
        "máximo cerca de 700 palavras, dividindo o espaço igualmente entre eles."
    )
    conteudo = [{"type": "text", "text": instrucao}]
    for caminho in caminhos:
        conteudo.append({
            "type": "image_url",
            "image_url": {"url": _imagem_para_data_url(caminho)},
        })

    extra = {"reasoning_effort": VISAO_REASONING_EFFORT} if VISAO_REASONING_EFFORT else None
    resposta = client.chat.completions.create(
        model=MODELO_VISAO,
        messages=[{"role": "user", "content": conteudo}],
        extra_body=extra,
    )
    return resposta.choices[0].message.content


def _redigir_com_gpt_oss(prompt: str, descricoes: str) -> str:
    """Etapa 2: o gpt-oss-120b redige o texto final usando as descrições."""
    mensagem = (
        "Abaixo estão descrições de imagens feitas por um modelo de visão.\n\n"
        f"{descricoes}\n\n"
        f"Siga esta solicitação:\n{prompt}"
    )
    resposta = client.chat.completions.create(
        model=MODELO_ANALISE,
        messages=[{"role": "user", "content": mensagem}],
        extra_body={"reasoning_effort": ANALISE_REASONING_EFFORT},
    )
    return resposta.choices[0].message.content


def _salvar_txt(texto: str, destino: Path) -> Path:
    """Escreve apenas o texto da descrição no .txt (sobrescreve se já existir)."""
    destino.write_text(texto.strip() + "\n", encoding="utf-8")
    return destino


def analisar_imagens(caminhos: list[str], prompt: str = PROMPT_PADRAO) -> dict:
    """Descreve os dados das imagens e salva só a descrição em AnaliseDeImagem.txt."""
    if not caminhos:
        return {"sucesso": False, "mensagem": "Nenhum caminho de imagem informado."}

    # Etapa 1: descrições do modelo de visão, em lotes
    descricoes = []
    for i in range(0, len(caminhos), MAX_IMAGENS_POR_REQUISICAO):
        lote = caminhos[i:i + MAX_IMAGENS_POR_REQUISICAO]
        try:
            texto = _descrever_com_visao(lote)
            descricoes.append(f"[Imagens: {', '.join(lote)}]\n{texto}")
        except Exception as e:
            return {"sucesso": False, "mensagem": f"Erro na etapa de visão: {e}"}

    descricoes_texto = "\n\n".join(descricoes)

    # Etapa 2: redação final
    try:
        analise = _redigir_com_gpt_oss(prompt, descricoes_texto)
    except Exception as e:
        return {
            "sucesso": False,
            "mensagem": f"Erro na etapa de análise: {e}",
            "descricoes": descricoes_texto,
        }

    # Etapa 3: salvar no .txt
    try:
        arquivo = _salvar_txt(analise, ARQUIVO_SAIDA)
    except Exception as e:
        return {
            "sucesso": False,
            "mensagem": f"Erro ao salvar o arquivo: {e}",
            "analise": analise,
        }

    return {"sucesso": True, "arquivo": str(arquivo), "analise": analise}


# Definições das tools (formato da API da Anthropic). Ajuste se seu framework usar outro.
TOOLS = [
    {
        "name": "selecionar_imagens",
        "description": "Abre uma janela para o usuário selecionar uma ou mais imagens do computador. "
                       "Retorna caminho, formato e dimensões de cada imagem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título da janela (opcional)."}
            },
            "required": [],
        },
    },
    {
        "name": "analisar_imagens",
        "description": "Descreve os dados e informações presentes nas imagens e salva "
                       "apenas essa descrição no arquivo AnaliseDeImagem.txt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "caminhos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Caminhos das imagens (obtidos com selecionar_imagens).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Instrução opcional sobre o que destacar na descrição.",
                },
            },
            "required": ["caminhos"],
        },
    },
]

FUNCOES = {
    "selecionar_imagens": selecionar_imagens,
    "analisar_imagens": analisar_imagens,
}


if __name__ == "__main__":
    sel = selecionar_imagens()
    if not sel["sucesso"]:
        print(sel["mensagem"])
    else:
        caminhos = [im["caminho"] for im in sel["imagens"] if "erro" not in im]
        print("Analisando imagens, aguarde...")
        saida = analisar_imagens(caminhos)
        if saida["sucesso"]:
            print(f"Pronto! Descrição salva em: {saida['arquivo']}")
        else:
            print(saida["mensagem"])