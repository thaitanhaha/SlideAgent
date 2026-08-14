import copy
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Callable, List
import yaml

from conclusion_generator import ConclusionGenerator
from file_utils import ReportTask
from pptx_parser2 import PptxParser
from document_extractor import DocumentDataExtractor
from document_processor import DocumentProcessor
from tools_selector import ToolSelector
from tool_functions import *

class YamlProcessor:
    def __init__(self, task: ReportTask, document_processor: DocumentProcessor, document_extractor: DocumentDataExtractor, tool_selector: ToolSelector, conclusion_generator: ConclusionGenerator):
        self.task = task
        self.document_processor = document_processor
        self.document_extractor = document_extractor
        self.tool_selector = tool_selector
        self.conclusion_generator = conclusion_generator
        self.pptx_parser = PptxParser(self.task.pptx_template_path)

    def create_timestamped_folder(self) -> Path:
        base = Path("data")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = base / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def load_yaml_data(self, yaml_path: Path):
        slide = self.pptx_parser.presentation.slides[0]
        data_list = self.pptx_parser._extract_pptx_elements1(slide)

        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            template_slide = data.get('template_slide', {})
            num = 0
            for i,element in enumerate(template_slide['elements']):
                if element.get('type') == 'chart' or element.get('type') == 'table':
                    template_slide['elements'][i]['data'] = data_list[num]
                    num+=1
            return template_slide

    def parse_ppt_structure(self) -> Dict[str, Any]:
        """
        Parses the structural layout of the template slide.
        """
        try:
            if hasattr(self.task, 'ground_truth_yaml_path') and self.task.ground_truth_yaml_path:
                return self.load_yaml_data(self.task.ground_truth_yaml_path)
            return self.pptx_parser.parse_slide_vlm(slide_idx=0)
        except Exception as e:
            print(f"[Error] Parsing PPT structure failed: {e}")
            return {}

    def extract_document_data_for_targets(
        self, 
        template_slides: Dict[str, Any], 
        target_indices: List[int], 
        document_text: str
    ) -> Path:
        """
        Reads the document text and extracts data only for the selected target elements.
        """
        data_path = self.create_timestamped_folder()
        retrieval_path = data_path / "retrieval"
        retrieval_path.mkdir(parents=True, exist_ok=True)

        try:
            instruction = getattr(self.task, 'query', 'Extract and update data')

            # Filter elements to only extract tables/charts identified in target_indices
            table_specs = []
            for idx, element in enumerate(template_slides.get('elements', [])):
                if idx in target_indices and element.get('type') in {'chart', 'table'}:
                    spec = {
                        'caption': element.get('caption', f'Target_Element_{idx}'),
                        'columns': element.get('data', {}).get('columns', ['col1', 'col2'])
                    }
                    table_specs.append(spec)

            if not table_specs:
                print("[Warning] No tables/charts were selected for updating.")
                return data_path

            # Call DocumentProcessor to save data to the data_path
            self.document_processor.extract_multiple_tables_from_document(
                document_text=document_text,
                table_specs=table_specs,
                instruction=instruction,
                data_path=data_path
            )
            print(f"[Success] Data extracted from document.")
            
        except Exception as e:
            print(f"[Error] During document extraction: {e}")
            
        return data_path

    def generate_conclusion(self, template_slides: Dict[str, Any], data_path: Path, document_text: str, target_indices: List[int]) -> Any:
        """
        Generates the updated conclusion/summary for the slide based on the newly extracted data.
        """
        try:
            output_slide = self.conclusion_generator.get_conclusion(
                query=self.task.query, 
                template_slide=template_slides,
                data_path=data_path,
                document_text=document_text,
                target_indices=target_indices
            )
            return output_slide
        except Exception as e:
            print(f"[Error] Generating conclusion failed: {e}")
            return ''

    def process_and_generate(self, document_path: str = None) -> Dict[str, Any]:
        """
        Parse Structure -> Select targets -> Document Data Extraction -> Slide Generation
        """
        template_slides = self.parse_ppt_structure()

        slide_params = self.document_extractor.process_slide_params(template_slides)

        target_indices = self.document_extractor.identify_target_elements(
            user_instruction=self.task.query,
            slide_params=slide_params
        )

        document_text = ""
        if document_path and Path(document_path).exists():
            document_text = self.document_processor.read_document(document_path)

        data_path = self.extract_document_data_for_targets(
            template_slides=template_slides,
            target_indices=target_indices,
            document_text=document_text 
        )

        output_slide = self.generate_conclusion(
            template_slides=copy.deepcopy(template_slides),
            data_path=data_path,
            document_text=document_text,
            target_indices=target_indices
        )

        return {
            'instruction': self.task.query,
            'target_elements': target_indices,
            'template_slide': template_slides,
            'output_slide': output_slide,
            'data_path': str(data_path)
        }

    def save_to_file(self, data: Dict[str, Any]):
        """
        Saves the processed slide output to a YAML file.
        """
        output_dir = self.task.ground_truth_yaml_path.parent
        output_filename = f"{self.task.ground_truth_yaml_path.stem}_generated_doc.yaml"
        output_path = output_dir / output_filename

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(
                copy.deepcopy(data),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                canonical=False,
                indent=2,
                width=float('inf'),
            )
        print(f"[Success] Generated YAML output file at: {output_path}\n")


