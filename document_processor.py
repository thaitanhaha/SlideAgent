import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from config import config
import PyPDF2
import docx
from file_utils import load_prompt_from_file


class DocumentProcessor:
    """
    DocumentProcessor class for reading documents (PDF, DOCX, TXT) and extracting tabular data 
    via LLMs, then saving the results as CSV files for downstream components.
    """

    def __init__(self, temperature: float = 0):
        self.model = ChatOpenAI(
            base_url=config.BASE_URL,
            api_key=config.API_KEY,
            temperature=temperature,
            model=config.MODEL_NAME
        )
        self.extract_prompt = self._create_table_extraction_prompt()

    def _create_table_extraction_prompt(self) -> ChatPromptTemplate:
        """
        System prompt that directs the LLM to extract data into a structured JSON table format.
        """
        system_prompt = load_prompt_from_file("extract_table_prompt.txt")
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            (
                "human", 
                "Reference Document:\n{document_text}\n\n"
                "User Request:\n{instruction}\n\n"
                "Target Table Specifications (Caption / Expected Columns):\n{table_spec}"
            )
        ])

    def read_document(self, file_path: str) -> str:
        """
        Reads textual content from various supported file formats.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = path.suffix.lower()
        if ext == '.pdf':
            return self._read_pdf(path)
        elif ext == '.docx':
            return self._read_docx(path)
        elif ext in ['.txt', '.md', '.csv']:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def _read_pdf(self, path: Path) -> str:
        text = []
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
        return "\n".join(text)

    def _read_docx(self, path: Path) -> str:
        doc = docx.Document(path)
        return "\n".join([paragraph.text for paragraph in doc.paragraphs])

    def _clean_json(self, raw_text: str) -> Dict[str, Any]:
        """
        Cleans the LLM output string to safely parse the JSON.
        """
        cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())

    def extract_multiple_tables_from_document(
        self, 
        document_text: str, 
        table_specs: List[Dict[str, Any]], 
        instruction: str, 
        data_path: Path
    ) -> Path:
        """
        Iterates through the target table specifications, extracts the corresponding data from the document text, 
        and saves them as CSV files (0.csv, 1.csv, etc.) in the 'retrieval' folder.
        """
        retrieval_path = Path(data_path) / "retrieval"
        retrieval_path.mkdir(parents=True, exist_ok=True)
        
        chain = self.extract_prompt | self.model

        for idx, spec in enumerate(table_specs):
            caption = spec.get('caption', f'Table {idx}')
            ori_idx = spec.get('idx', idx)
            print(f"[Info] Extracting data for table: {caption}...")
            csv_file_path = retrieval_path / f"{ori_idx}.csv"

            try:
                # Call the LLM to extract the data
                response = chain.invoke({
                    "document_text": document_text,
                    "instruction": instruction,
                    "table_spec": json.dumps(spec, ensure_ascii=False)
                })
                
                # Parse JSON and convert to a Pandas DataFrame
                extracted_data = self._clean_json(response.content)
                columns = extracted_data.get("columns", [])
                data_rows = extracted_data.get("data", [])
                
                if columns and data_rows:
                    df = pd.DataFrame(data_rows, columns=columns)
                else:
                    df = pd.DataFrame(data_rows)

                # Save the dataframe to a CSV file
                df.to_csv(csv_file_path, index=False, encoding='utf-8')
                print(f"       ✅ Successfully saved: {csv_file_path}")

            except Exception as e:
                print(f"       ❌ Error extracting table {idx} ({caption}): {e}")
                # Create an empty CSV file to prevent downstream crashing
                pd.DataFrame().to_csv(csv_file_path, index=False)

        return retrieval_path