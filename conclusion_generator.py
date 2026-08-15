import re
from copy import deepcopy
from math import hypot
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config import config
from file_utils import load_prompt_from_file


class ConclusionGenerator:
    """
    A class that generates conclusions based on template data and new input data using LLM.
    """
    def __init__(self, temperature: float = 0):
        """
        Initialize the ConclusionGenerator with specified temperature.

        Args:
            temperature (float): Temperature parameter for the LLM (default: 0)
        """
        self.model = ChatOpenAI(
            base_url=config.BASE_URL,
            api_key=config.API_KEY,
            temperature=temperature,
            model=config.MODEL_NAME
        )
        self.conclusion_prompt_template = self._create_conclusion_prompt_template()
        self.new_caption_prompt_template = self._create_new_caption_prompt_template()
        self.text_rewrite_prompt_template = self._create_text_rewrite_prompt_template()

    def _create_conclusion_prompt_template(self) -> ChatPromptTemplate:
        system_prompt = load_prompt_from_file("conclusion_prompt.txt")
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", """template_data:
                        {template_caption}
                        {template_data}
                        template_conclusion:    
                        {template_conclusion}

                        data:
                        {data_caption}
                        {data}
                        conclusion:
                            """)
        ])

    def _create_new_caption_prompt_template(self) -> ChatPromptTemplate:
        system_prompt = load_prompt_from_file("caption_prompt.txt")
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", """
                        table_template_caption: {template_caption}
                        params:{params}
                        table_caption:            
            """)
        ])

    def _create_text_rewrite_prompt_template(self) -> ChatPromptTemplate:
        system_prompt = load_prompt_from_file("text_rewrite_prompt.txt")
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Reference documents:\n{document_text}\n\nUser request:\n{user_instruction}\n\nOld text:\n{old_text}\n\nNew text:")
        ])

    def _nearest_point(self, point, points):
        px, py = point
        best_dist = float('inf')
        best_idx = -1

        for i, (x, y) in enumerate(points):
            d = hypot(x - px, y - py)
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    # def get_conclusion(self, query_filters: Dict, template_slide: Dict[str, Any], data_path: Path):
    #     try:
    #         base_path = Path(data_path)
    #         processed_path = base_path / "processed"
    #         processed_path.mkdir(parents=True, exist_ok=True)
    #         updated_elements = []
    #         elements = template_slide.get('elements', [])
    #         elements_table = [item for item in elements if
    #                           item.get('role') == 'table' or item.get('role') == 'chart-bar' or item.get(
    #                               'role') == 'chart-line']
    #         updated_conclusion = []
    #         for item in elements:
    #             if item.get('role') == 'slide-title' or item.get('role') == 'body-text':
    #                 updated_elements.append(deepcopy(item))
    #             if item.get('role') == 'caption':
    #                 params = {
    #                     'city': query_filters.get('city'),
    #                     'block': query_filters.get('block'),
    #                     'project': query_filters.get('project'),
    #                     'start_date': query_filters.get('start_date'),
    #                     'end_date': query_filters.get('end_date')
    #                 }
    #                 get_new_caption_chain = self.new_caption_prompt_template | self.model
    #                 try:
    #                     caption_content = get_new_caption_chain.invoke(
    #                         {"template_caption": item.get("text"), "params": params}).content

    #                     caption_content = re.sub(r'<think>.*?</think>', '', caption_content, flags=re.DOTALL).strip()

    #                 except Exception as e:
    #                     print(f"Error: Failed to get new table title: {e}")

    #                 caption_point = (item.get('layout').get('x'), item.get('layout').get('y'))
    #                 table_points = []
    #                 for elements_table_layout in elements_table:
    #                     table_points.append((elements_table_layout.get('layout').get('x'), elements_table_layout.get('layout').get('y')))
    #                 best_idx = self._nearest_point(caption_point, table_points)
    #                 template_slide_table_data = elements_table[best_idx]
    #                 out_slide_table_data = pd.read_excel(processed_path / "0.xlsx")
    #                 chain = self.conclusion_prompt_template | self.model
    #                 template_conclusion = [d["text"] for d in updated_elements if d['role'] == 'body-text']
    #                 try:
    #                     response = chain.invoke(
    #                         {"template_caption": item.get("text"), "template_data": template_slide_table_data.get("data"),
    #                          "template_conclusion": template_conclusion[0],
    #                          "data_caption": caption_content,
    #                          "data": out_slide_table_data
    #                          })
    #                 except Exception as e:
    #                     print(f"Error: Failed to get new table summary: {e}")

    #                 conclusion = response.content.replace('*', '')
    #                 conclusion = re.sub(r'<think>.*?</think>', '', conclusion, flags=re.DOTALL).strip()
    #                 updated_conclusion.append(conclusion)

    #                 item['text'] = caption_content
    #                 template_slide_table_data['data'] = deepcopy(out_slide_table_data.to_dict('records'))

    #                 updated_elements.append(deepcopy(item))
    #                 updated_elements.append(deepcopy(template_slide_table_data))
    #                 break

    #         updated_elements[1]['text'] = deepcopy(updated_conclusion[0])

    #         output_slide = {
    #             "slide_size": deepcopy(template_slide.get("slide_size")),
    #             "elements": updated_elements,
    #         }
    #         return output_slide
    #     except Exception as e:
    #         return ""

    def get_conclusion(self, query: str, template_slide: Dict[str, Any], data_path: Path, document_text: str, target_indices: List[int]) -> Dict[str, Any]:
        #TODO check
        try:
            base_path = Path(data_path)
            retrieval_path = base_path / "retrieval"
            
            elements = deepcopy(template_slide.get('elements', []))
            
            # Classify elements
            elements_table = []
            table_points = []
            body_text_element = None
            
            for idx, item in enumerate(elements):
                item['_original_idx'] = idx # Save original index to map with CSV file
                if item.get('role') in {'table', 'chart-bar', 'chart-line'}:
                    elements_table.append(item)
                    table_points.append((item.get('layout').get('x'), item.get('layout').get('y')))
                elif item.get('role') == 'body-text':
                    body_text_element = item

            template_conclusion = body_text_element.get("text", "") if body_text_element else ""
            updated_conclusion = ""

            # Update 
            for item in elements:
                original_idx = item.get('_original_idx', -1)
                role = item.get('role', '')
                # A. Change text
                if role in {'slide-title', 'body-text', 'text'} and original_idx in target_indices:
                    try:
                        rewrite_chain = self.text_rewrite_prompt_template | self.model
                        response = rewrite_chain.invoke({
                            "document_text": document_text,
                            "user_instruction": query,
                            "old_text": item.get("text", "")
                        })
                        new_text = re.sub(r'<think>.*?</think>', '', response.content, flags=re.DOTALL).strip()
                        item['text'] = new_text.replace('*', '')
                    except Exception as e:
                        print(f"[Error] Failed to rewrite text for {role}: {e}")
                # B. Change table
                if role == 'caption':
                    # 1. Find the nearest table/chart to this caption
                    caption_point = (item.get('layout').get('x'), item.get('layout').get('y'))
                    if not table_points:
                        continue

                    best_idx = self._nearest_point(caption_point, table_points)
                    target_table = elements_table[best_idx]
                    table_original_idx = target_table['_original_idx']

                    # 2. Read new data from the retrieval folder (CSV file corresponding to the index)
                    csv_file = retrieval_path / f"{table_original_idx}.csv"
                    if csv_file.exists():

                        # 3. Generate new caption
                        try:
                            caption_chain = self.new_caption_prompt_template | self.model
                            caption_content = caption_chain.invoke({
                                "template_caption": item.get("text"), 
                                "user_instruction": query
                            }).content
                            caption_content = re.sub(r'<think>.*?</think>', '', caption_content, flags=re.DOTALL).strip()
                            item['text'] = caption_content
                        except Exception as e:
                            print(f"[Error] Failed to generate new caption: {e}")
                            caption_content = item.get("text")

                        # 4. Generate new conclusion
                        try:
                            new_data_df = pd.read_csv(csv_file)
                            if not updated_conclusion and template_conclusion:
                                conclusion_chain = self.conclusion_prompt_template | self.model
                                response = conclusion_chain.invoke({
                                    "template_caption": item.get("text"), 
                                    "template_data": target_table.get("data"),
                                    "template_conclusion": template_conclusion,
                                    "data_caption": caption_content,
                                    "data": new_data_df.to_string(index=False)
                                })
                                updated_conclusion = response.content.replace('*', '')
                                updated_conclusion = re.sub(r'<think>.*?</think>', '', updated_conclusion, flags=re.DOTALL).strip()

                            # 5. Update data into the table
                            target_table['data'] = new_data_df.to_dict('records')
                        except Exception as e:
                            print(f"[Error] Failed to process table data or conclusion: {e}")

            # Remove temporary indices and update the conclusion into body-text
            for item in elements:
                if '_original_idx' in item:
                    del item['_original_idx']
                if item.get('role') == 'body-text' and updated_conclusion:
                    item['text'] = updated_conclusion

            return {
                "slide_size": deepcopy(template_slide.get("slide_size")),
                "elements": elements,
            }
        except Exception as e:
            print(f"[Error] in get_conclusion: {e}")
            return template_slide

