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
        print(response_content)
        response_content = _clean_and_parse_json(response_content)
        return response_content
        a = """```json
[
  {
    "shape_type": "slide-title",
    "content": "Definition and Types",
    "bbox": [57, 86, 483, 160]
  },
  {
    "shape_type": "body-text",
    "content": "Machine learning is a part of artificial intelligence.\\nIt lets computers learn from data and get better over time without writing exact rules for every task.\\nInstead of hard-coding instructions, programmers feed data into a system so it can find patterns and make its own choices or guesses.",
    "bbox": [126, 223, 792, 473]
  },
  {
    "shape_type": "caption",
    "content": "Main types of machine learning",
    "bbox": [353, 903, 642, 930]
  },
  {
    "shape_type": "table",
    "content": "Types | Properties | Year\\nSupervised learning | Uses data that already has the correct answers (labels) to teach the system how to predict outcomes for new data. | 1950s\\nUnsupervised learning | Looks at data without any labels to find hidden groups or patterns on its own. | 1960s\\nReinforcement learning | Learns by trial and error, getting rewards for good moves and penalties for bad ones",
    "bbox": [50, 542, 915, 876]
  }
]
```"""
        return _clean_and_parse_json(a)
    except Exception as e:
        print(f"Failed to call vision model or parse JSON: {e}")
        return []


    