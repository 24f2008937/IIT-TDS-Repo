from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
import sys
from io import StringIO
import traceback
import json
import re
from openai import OpenAI


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI()


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Request model
# ---------------------------------------------------------

class CodeRequest(BaseModel):
    code: str


# ---------------------------------------------------------
# Execute submitted Python code
# ---------------------------------------------------------

def execute_python_code(code: str) -> dict:
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        # Execute the submitted code in a fresh namespace
        exec(code, {})

        output = sys.stdout.getvalue()

        return {
            "success": True,
            "output": output
        }

    except Exception:
        output = traceback.format_exc()

        return {
            "success": False,
            "output": output
        }

    finally:
        sys.stdout = old_stdout


# ---------------------------------------------------------
# Identify error line
# ---------------------------------------------------------

def analyze_error_with_ai(code: str, traceback_str: str) -> List[int]:
    """
    First extract the failing line directly from Python's traceback.

    Example:
        File "<string>", line 3, in <module>

    -> [3]

    If direct extraction fails, use AI as a fallback.
    """

    # -----------------------------------------------------
    # 1. Direct traceback extraction
    # -----------------------------------------------------

    matches = re.findall(
        r'File "<string>", line (\d+)',
        traceback_str
    )

    if matches:
        return [int(line) for line in matches]


    # -----------------------------------------------------
    # 2. AI fallback
    # -----------------------------------------------------

    try:
        token = (
            os.environ.get("AIPIPE_TOKEN")
            or os.environ.get("OPENAI_API_KEY")
        )

        if not token:
            print("No AIPIPE_TOKEN or OPENAI_API_KEY found.")
            return []

        client = OpenAI(
            base_url="https://aipipe.org/openai/v1",
            api_key=token
        )

        prompt = f"""
Analyze the following Python code and traceback.

Identify the line number or line numbers where the error occurred.

Return ONLY valid JSON in exactly this format:

{{
    "error_lines": [3]
}}

CODE:
{code}

TRACEBACK:
{traceback_str}
"""

        response = client.chat.completions.create(
            model="openai/gpt-4.1-nano",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content

        print(f"DEBUG: AI response content: {content}")

        data = json.loads(content)

        error_lines = data.get("error_lines", [])

        return [
            int(line)
            for line in error_lines
            if isinstance(line, (int, float))
        ]

    except Exception as e:
        print(
            f"AI Error Analysis Exception: {repr(e)}"
        )
        print(traceback.format_exc())

        return []


# ---------------------------------------------------------
# Code interpreter endpoint
# ---------------------------------------------------------

@app.post("/code-interpreter")
@app.post("")
async def code_interpreter(req: CodeRequest):

    # Execute submitted code
    exec_result = execute_python_code(req.code)


    # -----------------------------------------------------
    # Successful execution
    # -----------------------------------------------------

    if exec_result["success"]:

        return {
            "error": [],
            "result": exec_result["output"]
        }


    # -----------------------------------------------------
    # Failed execution
    # -----------------------------------------------------

    error_lines = analyze_error_with_ai(
        req.code,
        exec_result["output"]
    )

    return {
        "error": error_lines,
        "result": exec_result["output"]
    }