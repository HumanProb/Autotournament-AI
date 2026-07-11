import os
import chromadb
from PyPDF2 import PdfReader
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Initialize local Vector Database
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="tournament_rules")

def ingest_rulebook(pdf_path: str):
    """Reads a PDF rulebook and saves it into the Vector Database."""
    print(f"📖 Reading {pdf_path}...")
    reader = PdfReader(pdf_path)
    
    chunks = []
    # Simple chunking: split by paragraphs
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            paragraphs = text.split("\n\n")
            for p in paragraphs:
                if len(p.strip()) > 50: # Ignore tiny fragments
                    chunks.append({"text": p.strip(), "page": i + 1})

    print(f"🧠 Encoding {len(chunks)} rule chunks into Vector Space...")
    
    # We use Chroma's default embedding model for speed
    documents = [c["text"] for c in chunks]
    metadatas = [{"page": c["page"]} for c in chunks]
    ids = [f"chunk_{i}" for i in range(len(chunks))]

    # Upsert into database
    collection.upsert(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    print("✅ Rulebook successfully memorized!")

def ask_rulebook(question: str) -> str:
    """Searches the rulebook and uses Gemini to answer the question."""
    # 1. Search the Vector Database for the 3 most relevant paragraphs
    results = collection.query(
        query_texts=[question],
        n_results=3
    )
    
    if not results['documents'][0]:
        return "I couldn't find anything about that in the rulebook."

    # 2. Package the retrieved rules into a context string
    context = ""
    for idx, doc in enumerate(results['documents'][0]):
        page = results['metadatas'][0][idx]['page']
        context += f"[Page {page}]: {doc}\n\n"

    # 3. Ask Gemini to read those specific rules and answer the player
    prompt = f"""You are the official Head Admin for this esports tournament.
    A player has asked a question. Answer them accurately and professionally 
    based ONLY on the rulebook excerpts provided below. 
    
    If the answer is not in the excerpts, say "I cannot find a specific rule for that, please ping a human admin."
    
    Player Question: "{question}"
    
    Rulebook Excerpts:
    {context}
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt # Whatever variable you are passing as the prompt
    )
    
    return response.text