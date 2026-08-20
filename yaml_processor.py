import copy
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import yaml

from conclusion_generator import ConclusionGenerator
from file_utils import ReportTask
from pptx_parser2 import PptxParser
from document_extractor import DocumentDataExtractor
from document_processor import DocumentProcessor

class YamlProcessor:
    def __init__(self, task: ReportTask, document_processor: DocumentProcessor, document_extractor: DocumentDataExtractor, conclusion_generator: ConclusionGenerator):
        self.task = task
        self.document_processor = document_processor
        self.document_extractor = document_extractor
        self.conclusion_generator = conclusion_generator
        self.pptx_parser = PptxParser(self.task.pptx_template_path)

    def create_timestamped_folder(self) -> Path:
        base = Path("data")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = base / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def load_yaml_data(self, yaml_path: Path, slide_idx: int = 0):
        slide = self.pptx_parser.presentation.slides[slide_idx]
        data_list = self.pptx_parser._extract_pptx_elements1(slide)

        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            template_slide = data.get('template_slide', {})
            template_slide = template_slide[0]
            num = 0
            for i,element in enumerate(template_slide['elements']):
                if element.get('type') == 'chart' or element.get('type') == 'table':
                    template_slide['elements'][i]['data'] = data_list[num]
                    num+=1
            return template_slide

    def parse_ppt_structure(self, slide_idx: int) -> Dict[str, Any]:
        """
        Parses the structural layout of a specific slide index.
        """
        try:
            if hasattr(self.task, 'ground_truth_yaml_path') and self.task.ground_truth_yaml_path:
                return self.load_yaml_data(self.task.ground_truth_yaml_path, slide_idx)
            return self.pptx_parser.parse_slide_vlm(slide_idx=slide_idx)
            # #TODO hard code
            # if slide_idx == 0:
            #     return self.load_yaml_data("slides/test_1.yaml", 0)
            # if slide_idx == 1:
            #     return self.load_yaml_data("slides/test_2.yaml", 1)
            # if slide_idx == 2:
            #     return self.load_yaml_data("slides/test_3.yaml", 2)
        except Exception as e:
            print(f"[Error] Parsing PPT structure failed for slide {slide_idx}: {e}")
            return {}

    def extract_document_data_for_targets(
        self, 
        template_slides: Dict[str, Any], 
        target_indices: List[int], 
        document_text: str,
        slide_data_path: Path
    ) -> Path:
        """
        Reads the document text and extracts data only for the selected target tables/charts.
        """
        retrieval_path = slide_data_path / "retrieval"
        retrieval_path.mkdir(parents=True, exist_ok=True)

        try:
            instruction = getattr(self.task, 'query', 'Extract and update data')

            # Filter elements to only extract tables/charts identified in target_indices
            table_specs = []
            for idx, element in enumerate(template_slides.get('elements', [])):
                if idx in target_indices and element.get('type') in {'chart', 'table'}:
                    print("A---", element)
                    data = element.get('data', [])
                    columns = list(data[0].keys()) if data and isinstance(data, list) and isinstance(data[0], dict) else ['col1', 'col2']
                    spec = {
                        'caption': element.get('caption', f'Target_Element_{idx}'),
                        # 'columns': element.get('data', {}).get('columns', ['col1', 'col2'])
                        'columns': columns
                    }
                    table_specs.append(spec)

            if not table_specs:
                print("[Warning] No tables/charts were selected for updating.")
                return slide_data_path

            print("TABLE SPECS", table_specs)
            # Call DocumentProcessor to save data to the data_path
            self.document_processor.extract_multiple_tables_from_document(
                document_text=document_text,
                table_specs=table_specs,
                instruction=instruction,
                data_path=slide_data_path
            )
            print(f"[Success] Data extracted from document.")
            
        except Exception as e:
            print(f"[Error] During document extraction: {e}")
            
        return slide_data_path

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

    def process_and_generate(self) -> Dict[str, Any]:
        """
        Parse Structure -> Select targets -> Document Data Extraction -> Slide Generation
        """
        document_text = ""
        document_path = self.task.document_path
        if document_path and Path(document_path).exists():
            document_text = self.document_processor.read_document(document_path)

        num_slides = len(self.pptx_parser.presentation.slides)
        print(f"[Info] Found {num_slides} slides to process.")

        base_data_path = self.create_timestamped_folder()

        # =================
        # GLOBAL SCAN
        # =================
        all_template_slides = []
        global_slide_params = []
        id_mapping = {}
        global_counter = 0

        for slide_idx in range(num_slides):
            template_slide = self.parse_ppt_structure(slide_idx=slide_idx)
            all_template_slides.append(template_slide)
            
            if not template_slide or "error" in template_slide:
                continue

            slide_params = self.document_extractor.process_slide_params(template_slide)
            
            for param in slide_params:
                param_copy = param.copy()
                param_copy['global_index'] = global_counter
                param_copy['slide_index'] = slide_idx
                global_slide_params.append(param_copy)
                
                id_mapping[global_counter] = {
                    'slide_idx': slide_idx, 
                    'element_index': param['element_index']
                }
                global_counter += 1

        # =================
        # GLOBAL TARGETING
        # =================
        
        global_target_indices = self.document_extractor.identify_global_target_elements(
            user_instruction=self.task.query,
            document_text=document_text,
            global_slide_params=global_slide_params
        )
        
        slide_targets_map = {i: [] for i in range(num_slides)}
        for g_idx in global_target_indices:
            if g_idx in id_mapping:
                s_idx = id_mapping[g_idx]['slide_idx']
                e_idx = id_mapping[g_idx]['element_index']
                slide_targets_map[s_idx].append(e_idx)

        # =================
        # LOCAL EXECUTION
        # =================
        all_output_slides = []
        all_target_elements = []

        for slide_idx in range(num_slides):
            template_slide = all_template_slides[slide_idx]
            target_indices = slide_targets_map[slide_idx]
            all_target_elements.append(target_indices)

            if not template_slide or "error" in template_slide:
                all_output_slides.append(template_slide)
                continue
                
            print(f"-> Updating slide {slide_idx + 1}/{num_slides}")

            if not target_indices:
                all_output_slides.append(copy.deepcopy(template_slide))
                continue

            slide_data_path = base_data_path / f"slide_{slide_idx}"
            slide_data_path.mkdir(parents=True, exist_ok=True)

            self.extract_document_data_for_targets(
                template_slides=template_slide,
                target_indices=target_indices,
                document_text=document_text,
                slide_data_path=slide_data_path
            )

            output_slide = self.generate_conclusion(
                template_slides=copy.deepcopy(template_slide),
                data_path=slide_data_path,
                document_text=document_text,
                target_indices=target_indices
            )
            all_output_slides.append(output_slide)

        return {
            'instruction': self.task.query,
            'target_elements': all_target_elements,
            'template_slides': all_template_slides,
            'output_slides': all_output_slides,
            'data_path': str(base_data_path)
        }

    def save_to_file(self, data: Dict[str, Any]):
        """
        Saves the processed multi-slide output to a YAML file.
        """
        # output_dir = self.task.ground_truth_yaml_path.parent
        # output_filename = f"{self.task.ground_truth_yaml_path.stem}_generated_doc.yaml"
        # output_path = output_dir / output_filename
        output_dir = self.task.pptx_template_path.parent
        output_filename = f"{self.task.pptx_template_path.stem}_generated_doc.yaml"
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
        print(f"\n[Success] Generated multi-slide YAML output file at: {output_path}\n")