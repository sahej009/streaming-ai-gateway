import json
import time
import argparse
import httpx
import os
import asyncio
import math
from datasets import Dataset

from dotenv import load_dotenv
load_dotenv() 

# 👇 NEW: Import standard OpenAI and Ragas's new llm_factory
from openai import OpenAI
from ragas.llms import llm_factory

from langchain_huggingface import HuggingFaceEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper

from ragas import evaluate
from ragas.run_config import RunConfig
from ragas.metrics import Faithfulness


API_URL = "http://localhost:8000/chat/stream"
DATASET_PATH = "evals/golden_dataset.json"
RESULTS_DIR = "evals/results"

def load_dataset():
    with open(DATASET_PATH, "r") as f:
        return json.load(f)

async def ask_gateway(question: str, version: str) -> str:
    """Calls your local FastAPI gateway to get the LLM's response."""
    payload = {
        "message": question,
        "session_id": "eval-session",
        "prompt_version": version
    }
    
    full_response = ""
    with httpx.stream("POST", API_URL, json=payload, timeout=30.0) as response:
        for chunk in response.iter_text():
            if chunk.startswith("data: ") and "[DONE]" not in chunk:
                full_response += chunk.replace("data: ", "").strip() + " "
                
    return full_response.strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=str, required=True, help="Prompt version to evaluate")
    args = parser.parse_args()

    print(f"🚀 Starting evaluation for version: {args.version}")
    golden_data = load_dataset()
    
    questions, contexts, ground_truths, answers = [], [], [], []

    print("🤖 Fetching answers from the API...")
    for item in golden_data:
        question = item["question"]
        print(f"   -> Asking: {question}")
        answer = asyncio.run(ask_gateway(question, args.version))
        
        questions.append(question)
        contexts.append([item["context"]])
        ground_truths.append(item["expected_answer"])
        answers.append(answer)

    dataset = Dataset.from_dict({
        "question": questions,
        "contexts": contexts,
        "answer": answers,
        "ground_truth": ground_truths
    })

    print("🧠 Booting up Judge LLM (Groq 70b via OpenAI standard) and Embeddings...")
    
    # 👇 NEW: Create an OpenAI client but point its URL to Groq!
    groq_client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1"
    )
    # Pass the Groq client into Ragas's new factory
    ragas_llm = llm_factory(model="llama-3.3-70b-versatile", client=groq_client)

    # We can safely ignore the deprecation warning for embeddings for now
    judge_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    ragas_emb = LangchainEmbeddingsWrapper(judge_embeddings)

    config = RunConfig(max_workers=1, max_retries=3)

    faithfulness_metric = Faithfulness(llm=ragas_llm)

    print("📊 Running Ragas evaluation (This will take 1-2 minutes)...")
    result = evaluate(
        dataset,
        # 👇 FIX: Pass the initialized object variable here
        metrics=[faithfulness_metric], 
        llm=ragas_llm,
        embeddings=ragas_emb,
        run_config=config,
        raise_exceptions=False
    )
    
    score_data = result.to_pandas().to_dict(orient="records")
    
    # Safely calculate mean, ignoring any rows that failed (NaN)
    valid_scores = [
        row["faithfulness"] 
        for row in score_data 
        if not math.isnan(row.get("faithfulness", float('nan')))
    ]
    mean_faithfulness = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
    
    print(f"\n✅ Evaluation Complete! Mean Faithfulness: {mean_faithfulness:.2f}")

    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
        
    timestamp = int(time.time())
    report_filename = f"{RESULTS_DIR}/{args.version}_{timestamp}.json"
    
    report_payload = {
        "version": args.version,
        "timestamp": timestamp,
        "mean_faithfulness": mean_faithfulness,
        "results": score_data
    }
    
    with open(report_filename, "w") as f:
        json.dump(report_payload, f, indent=2)
        
    print(f"📁 Report saved to {report_filename}")

if __name__ == "__main__":
    main()