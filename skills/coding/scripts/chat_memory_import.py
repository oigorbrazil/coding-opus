"""Import text messages from explicit exports, without accessing accounts or extracting ZIPs."""

import datetime as dt
import json
import zipfile

from brain import BrainError

MAX_EXPORT_BYTES = 100 * 1024 * 1024


def load_export(path):
    if path.stat().st_size > MAX_EXPORT_BYTES:
        raise BrainError("Exportação acima de 100 MiB. Divida o arquivo antes de importar.")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entries = [entry for entry in archive.infolist() if entry.filename.split("/")[-1] == "conversations.json"]
            if len(entries) != 1 or entries[0].file_size > MAX_EXPORT_BYTES:
                raise BrainError("O ZIP deve conter exatamente um conversations.json de até 100 MiB.")
            return json.loads(archive.read(entries[0]).decode("utf-8-sig"))
    return json.loads(path.read_text(encoding="utf-8-sig"))


def message_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(message_text(part) for part in value if isinstance(part, (str, dict)))
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
        if "parts" in value:
            return message_text(value["parts"])
        return "[Conteúdo não textual. Consulte o anexo na conversa original.]"
    return ""


def timestamp(value):
    if isinstance(value, (float, int)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()
    return value if isinstance(value, str) else ""


def chatgpt_messages(chat):
    mapping = chat.get("mapping")
    if not isinstance(mapping, dict):
        raise BrainError("Conversa ChatGPT sem mapping")
    current = chat.get("current_node")
    if not current:
        leaves = [key for key, node in mapping.items() if not node.get("children")]
        if len(leaves) != 1:
            raise BrainError("Conversa ChatGPT com ramificações sem current_node. Selecione a ramificação na exportação.")
        current = leaves[0]
    chain, seen = [], set()
    while current:
        if current in seen or current not in mapping:
            raise BrainError("Árvore de mensagens ChatGPT inválida")
        seen.add(current)
        node = mapping[current]
        chain.append(node.get("message"))
        current = node.get("parent")
    return list(reversed(chain))


def normalize(chat, format_name, project):
    if not isinstance(chat, dict):
        raise BrainError("Conversa inválida")
    source_id = chat.get("uuid") or chat.get("id") or chat.get("conversation_id")
    if not source_id:
        raise BrainError("Conversa sem identificador estável")
    if format_name == "claude":
        rows = chat.get("chat_messages")
        agent = "claude-web"
    elif format_name == "chatgpt":
        rows = chatgpt_messages(chat)
        agent = "chatgpt"
    else:
        rows = chat.get("messages")
        agent = str(chat.get("agent") or "other")
    if not isinstance(rows, list):
        raise BrainError("Lista de mensagens ausente")
    messages = []
    for index, row in enumerate(rows):
        if row is None:
            continue
        if not isinstance(row, dict):
            raise BrainError("Mensagem inválida na exportação")
        author = row.get("author") or {}
        if not isinstance(author, dict):
            raise BrainError("Autor inválido na exportação")
        role = row.get("sender") or row.get("role") or author.get("role")
        role = "user" if role == "human" else role
        if role not in ("user", "assistant"):
            continue
        content = row.get("text") or row.get("content")
        text = message_text(content)
        if text:
            messages.append({"id": "import:" + str(row.get("uuid") or row.get("id") or index),
                             "role": role, "content": text,
                             "timestamp": timestamp(row.get("created_at") or row.get("create_time") or row.get("timestamp"))})
    return {"agent": agent, "source_session": str(source_id),
            "project": project or str(chat.get("project_path") or ""),
            "messages": messages, "title": str(chat.get("name") or chat.get("title") or "Conversa importada")}


def import_chats(memory, path, format_name, project=""):
    data = load_export(path)
    chats = data.get("conversations") if isinstance(data, dict) and "conversations" in data else data
    if isinstance(chats, dict):
        chats = [chats]
    if not isinstance(chats, list):
        raise BrainError("Use uma conversa ou uma lista de conversas em JSON.")
    # Validate the whole export before the first write. Each conversation is a retryable transaction.
    conversations = [normalize(chat, format_name, project) for chat in chats]
    ids = [memory.save(**chat) for chat in conversations if chat["messages"]]
    return {"sessions": ids, "conversations": len(ids), "skipped_empty": len(chats) - len(ids),
            "note": "Texto importado. Anexos binários permanecem na origem. ChatGPT usa a ramificação ativa."}
