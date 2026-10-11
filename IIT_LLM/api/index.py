from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
import sys
from io import StringIO
import traceback
from openai import OpenAI

app = FastAPI()

# Enable CORS for all origins and methods
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Access-Control-Allow-Origin"],
)

class CodeRequest(BaseModel):
    code: str

class ErrorAnalysis(BaseModel):
    error_lines: List[int]

def execute_python_code(code: str) -> dict:
    """
    Execute Python code and return exact output or traceback.
    """
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
    """
    Use OpenAI-compatible client via AI Pipe proxy with structured output to identify error line numbers.
    """
    # Configure client to use AI Pipe proxy base URL and AIPIPE_TOKEN as API key
    client = OpenAI(
        base_url="https://aipipe.org/openai/v1",
        api_key=os.environ.get("AIPIPE_TOKEN") or os.environ.get("OPENAI_API_KEY")
    )

    prompt = f"""
Analyze this Python code and its error traceback.
Identify the line number(s) where the error occurred.

CODE:
{code}

TRACEBACK:
{traceback_str}

Return the line number(s) where the error is located.
"""

    response = client.beta.chat.completions.parse(
        model="gpt-4.1-nano", # Or use your preferred AI Pipe model
        messages=[{"role": "user", "content": prompt}],
        response_format=ErrorAnalysis,
    )

    return response.choices.message.parsed.error_lines

@app.post("/code-interpreter")
@app.post("")
async def code_interpreter(req: CodeRequest):
  exec_result = execute_python_code(req.code)

  if exec_result["success"]:
    return {"error": [], "result": exec_result["output"]}
  else:
    error_lines = analyze_error_with_ai(req.code, exec_result["output"])
    return {"error": error_lines, "result": exec_result["output"]}