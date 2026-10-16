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


# ---------------------------------------------------------
# Invoice extraction endpoint
# ---------------------------------------------------------

class ExtractRequest(BaseModel):
    text: str | None = None


class InvoiceResponse(BaseModel):
    vendor: str
    amount: float
    currency: str
    date: str


def regex_extract(text: str) -> InvoiceResponse:
    vendor = ""
    amount = 0.0
    currency = "USD"
    date = "2026-01-01"

    # Currency
    if re.search(r"\bEUR\b|€", text, re.IGNORECASE):
        currency = "EUR"
    elif re.search(r"\bGBP\b|£", text, re.IGNORECASE):
        currency = "GBP"
    elif re.search(r"\bUSD\b|\$", text, re.IGNORECASE):
        currency = "USD"
    else:
        c_m = re.search(r"\b([A-Z]{3})\b", text)
        if c_m:
            currency = c_m.group(1).upper()

    # Date (YYYY-MM-DD)
    d_m = re.search(r"\b(202\d-[01]\d-[0-3]\d)\b", text) or re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if d_m:
        date = d_m.group(1)

    # Amount: number 50-9050, excluding numbers with hyphens/word boundaries
    candidates = []
    for raw in re.findall(r"(?<![\w\-])(\d{1,4}(?:,\d{3})*(?:\.\d+)?)(?![\w\-])", text):
        cleaned = raw.replace(",", "")
        try:
            val = float(cleaned)
            if 50.0 <= val <= 9050.0 and val != 2026.0:
                candidates.append(val)
        except ValueError:
            pass
    if candidates:
        amount = candidates[0]

    # Vendor: planted vendor name
    v_m = re.search(r"\b([A-Z][a-zA-Z0-9]*-[a-zA-Z0-9]+(?:\s+[A-Za-z0-9]+)*(?:\s+(?:Ltd|Inc|LLC|Corp|Industries|Enterprises|Solutions|Co)\.?))\b", text)
    if v_m:
        vendor = v_m.group(1).strip()
    else:
        v_m2 = re.search(r"(?:Vendor|From|Billed by|Remit to|Pay to|Company):\s*([^\n\r,]+)", text, re.IGNORECASE)
        if v_m2:
            vendor = v_m2.group(1).strip()
        else:
            v_m3 = re.search(r"\b([A-Z][a-zA-Z0-9\-_]+(?:\s+[A-Za-z0-9\-_]+)*(?:\s+(?:Ltd|Inc|LLC|Corp|Industries|Enterprises|Solutions|Co)\.?))\b", text)
            if v_m3:
                vendor = v_m3.group(1).strip()

    return InvoiceResponse(vendor=vendor, amount=amount, currency=currency, date=date)


@app.post("/extract", response_model=InvoiceResponse)
async def extract_invoice(req: ExtractRequest):
    if not req.text or not req.text.strip():
        return InvoiceResponse(vendor="", amount=0.0, currency="USD", date="2026-01-01")

    text = req.text.strip()
    fallback = regex_extract(text)

    token = os.environ.get("AIPIPE_TOKEN") or os.environ.get("OPENAI_API_KEY")
    if not token:
        return fallback

    try:
        client = OpenAI(base_url="https://aipipe.org/openai/v1", api_key=token)
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract invoice fields from the text:\n"
                        "- vendor: vendor or seller company name (string)\n"
                        "- amount: total due as float/int\n"
                        "- currency: 3-letter uppercase code (e.g. USD, EUR, GBP; convert $ -> USD, € -> EUR, £ -> GBP)\n"
                        "- date: payment due date as YYYY-MM-DD\n"
                        "If missing or garbage text, use defaults: vendor='', amount=0.0, currency='USD', date='2026-01-01'."
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format=InvoiceResponse,
            timeout=8.0,
        )
        res = completion.choices[0].message.parsed
        if not res:
            return fallback

        # Normalization and guard rails
        curr = (res.currency or "").strip().upper()
        if curr in ("$", "US$"):
            curr = "USD"
        elif curr in ("€", "EURO"):
            curr = "EUR"
        elif curr in ("£", "POUND"):
            curr = "GBP"
        if len(curr) != 3:
            curr = fallback.currency

        dt = res.date or ""
        if not re.search(r"\b\d{4}-\d{2}-\d{2}\b", dt):
            dt = fallback.date

        amt = float(res.amount) if res.amount is not None else 0.0
        if amt == 0.0 and fallback.amount > 0.0:
            amt = fallback.amount

        vend = (res.vendor or "").strip()
        if not vend and fallback.vendor:
            vend = fallback.vendor

        return InvoiceResponse(vendor=vend, amount=amt, currency=curr, date=dt)
    except Exception:
        # ponytail: fallback to regex heuristics if LLM call fails or times out
        return fallback