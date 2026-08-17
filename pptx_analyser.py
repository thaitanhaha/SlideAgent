from openai import OpenAI
import json
from typing import List, Dict, Any
import re
from config import config
from file_utils import load_prompt_from_file, _clean_and_parse_json


def _call_vision_model_v2(base64_image: str) -> List[Dict[str, Any]]:

    client = OpenAI(
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
    )
    try:
        system_prompt = load_prompt_from_file("layout_parsing_prompt.txt")
        completion = client.chat.completions.create(
            # model="qwen25-vl",
            model=config.MODEL_NAME,
            messages=[{
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}]
            }, {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    {"type": "text",
                     "text": "Please analyze the slide content according to the system prompt, identify titles, summaries, and chart/table captions, and return JSON."}
                ],
            }],
        )
        response_content = completion.choices[0].message.content
        response_content = _clean_and_parse_json(response_content)
        return response_content
    except Exception as e:
        print(f"Failed to call vision model or parse JSON: {e}")
        return []


    