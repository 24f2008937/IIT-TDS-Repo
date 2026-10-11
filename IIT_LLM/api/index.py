from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
import sys
from io import StringIO
import traceback
import json
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Access-Control-Allow-Origin"],
)

class CodeRequest(BaseModel):
    code: str

def execute_python_code(code: str) -> dict:
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        exec(code)
        output = sys.stdout.getvalue()
        return {"success": True, "output": output}
    except Exception as e:
        output = traceback.format_exc()
        return {"success": False, "output": output}
    finally:
        sys.stdout = old_stdout

def analyze_error_with_ai(code: str, traceback_str: str) -> List[int]:
    try:
        client = OpenAI(
            base_url="https://aipipe.org/openai/v1",
            api_key=os.environ.get("AIPIPE_TOKEN") or os.environ.get("OPENAI_API_KEY")
        )

        prompt = f"""
Analyze this Python code and its error traceback.
Identify the line number(s) where the error occurred.
Return a JSON object with a single key "error_lines" containing a list of integer line numbers.

CODE:
{code}

TRACEBACK:
{traceback_str}
"""

        response = client.chat.completions.create(
            model="openai/gpt-4.1-nano",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("error_lines", [])
    except Exception:
        return []

@app.post("/code-interpreter")
@app.post("")
async def code_interpreter(req: CodeRequest):
    exec_result = execute_python_code(req.code)
    
    if exec_result["success"]:
        return {
            "error": [],
            "result": exec_result["output"]
        }
    else:
        error_lines = analyze_error_with_ai(req.code, exec_result["output"])
        return {
            "error": error_lines,
            "result": exec_result["output"]
        }