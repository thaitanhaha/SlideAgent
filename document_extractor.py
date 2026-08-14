import json
import re
import pandas as pd
from math import hypot
from typing import Any, Dict, List, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config import config
from file_utils import load_prompt_from_file


class DocumentDataExtractor:
    def __init__(self, temperature: float = 0):
        """
        Initializes the DocumentDataExtractor.
        """
        self.model = ChatOpenAI(
            base_url=config.BASE_URL,
            api_key=config.API_KEY,
            temperature=temperature,
            model=config.MODEL_NAME
        )
        self.target_selector_prompt_template = self._create_target_selector_prompt_template()
        self.extract_prompt_template = self._create_extract_prompt_template()

    def _create_target_selector_prompt_template(self) -> ChatPromptTemplate:
        """
        Creates the prompt to determine which slide elements should be updated based on the instruction.
        """
        system_prompt = load_prompt_from_file("identify_targets_prompt.txt")
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "List of slide elements:\n{available_elements}\n\nUser request:\n{user_instruction}")
        ])

    def _create_extract_prompt_template(self) -> ChatPromptTemplate:
        """
        Creates the prompt for reading the document and extracting the data.
        """
        system_prompt = load_prompt_from_file("extract_data_prompt.txt")
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Reference document:\n{document_text}\n\nUpdate request: {user_instruction}\n\nTarget table/chart structure:\n{slide_params}")
        ])

    def _clean_and_parse_json(self, raw_text: str) -> Any:
        """
        Removes <think> tags and markdown blocks to safely parse the JSON output.
        """
        cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())

    def _nearest_point(self, point, points):
        """
        Finds the nearest point from a list of points to the given point.

        Args:
            point: Target point as (x, y) tuple
            points: List of points as [(x1, y1), (x2, y2), ...]

        Returns:
            int: Index of the nearest point in the list
        """
        px, py = point
        best_dist = float('inf')
        best_idx = -1

        for i, (x, y) in enumerate(points):
            d = hypot(x - px, y - py)
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    def process_slide_params(self, template_slide: Dict[str, Any]):
        """
        Processes slide parameters by extracting caption and table/chart elements,
        matching them based on spatial proximity, and converting data to DataFrame format.
        Returns a list of dictionaries containing caption, row headers, and column headers.
        """
        elements = template_slide.get("elements", [])
        caption_temps = []
        table_temp = []
        points = []
        pairs = []

        slide_params = []

        for idx, element in enumerate(elements):
            element["_original_idx"] = idx
            role = element.get("role", "")
            if role in {'caption'}:
                caption_temps.append(element)
            if element.get("role") in {'table', 'chart-bar', 'chart-line'}:
                table_temp.append(element)
                points.append((element.get("layout").get('x'), element.get("layout").get('y')))
            if element.get("role") in {'slide-title', 'body-text', 'text'}:
                #TODO
                slide_params.append({
                    'caption': element.get("text", f"{role} element"),
                    'element_type': role,
                    'element_index': idx,
                    'row_headers': [],
                    'column_headers': []
                })

        for item in caption_temps:
            item_point = (item.get("layout").get('x'), item.get("layout").get('y'))
            nearest_point_idx = self._nearest_point(item_point, points)
            pairs.append((item, table_temp[nearest_point_idx]))

        for pair in pairs:
            data = pair[1].get('data')
            if not hasattr(data, 'columns'):
                if isinstance(data, list):
                    if data and isinstance(data[0], dict):
                        df = pd.DataFrame(data)
                    else:
                        cols = slide_params.get('columns')
                        df = pd.DataFrame(data, columns=cols) if cols else pd.DataFrame(data)
                elif isinstance(data, dict):
                    rows = data.get('rows')
                    cols = data.get('columns')
                    if rows is not None:
                        df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
                    else:
                        inner = data.get('data')
                        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                            df = pd.DataFrame(inner)
                        else:
                            df = pd.DataFrame(data)  # fallback
                else:
                    raise TypeError(f"Unsupported data type: {type(data)}")
            else:
                df = data
            if df.shape[1] < 1:
                raise ValueError("Expected at least 1 column of data")

            second_col_name = df.columns[0]
            df2 = df.set_index(second_col_name)

            column_headers = list(df2.columns)

            row_headers = list(df2.index)
            if df.shape[1] < 1:
                raise ValueError("Expected at least 1 column of data")

            #TODO
            dic = {
                'caption': pair[0].get("text"),
                'element_type': pair[1].get("role"),
                'element_index': pair[1].get("_original_idx"),
                'row_headers': row_headers,
                'column_headers': column_headers,
            }
            slide_params.append(dic)

        return slide_params


    def identify_target_elements(self, user_instruction: str, slide_params: List[Dict[str, Any]]) -> List[int]:
        """
        Uses the LLM to select the element indices that need to be changed based on the user instruction.
        """
        available_summary = [
            {
                "element_index": p.get("element_index"),
                "caption": p.get("caption"),
                "type": p.get("element_type")
            }
            for p in slide_params
        ]

        chain = self.target_selector_prompt_template | self.model
        try:
            response = chain.invoke({
                "available_elements": json.dumps(available_summary, ensure_ascii=False),
                "user_instruction": user_instruction
            })
            result = self._clean_and_parse_json(response.content)
            return result.get("target_indices", [])
        except Exception as e:
            print(f"[Warning] Failed to identify target elements ({e}). Defaulting to update all elements.")
            return [p.get("element_index") for p in slide_params]


        