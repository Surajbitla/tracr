# src/experiment_design/utils.py

import sys
import logging
from typing import Any, List, Tuple, Dict, Optional, Type
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from src.interface.bridge import DataUtilsInterface

logger = logging.getLogger(__name__)

class ClassificationUtils(DataUtilsInterface):
    def __init__(self, class_names_path: str, font_path: str):
        self.class_names = self.load_imagenet_classes(class_names_path)
        self.font_path = font_path

    @staticmethod
    def load_imagenet_classes(class_file_path: str) -> List[str]:
        try:
            with open(class_file_path, "r") as f:
                class_names = [line.strip() for line in f.readlines()]
            logger.info(f"Loaded {len(class_names)} ImageNet classes from {class_file_path}")
            return class_names
        except FileNotFoundError:
            logger.error(f"Class file not found at {class_file_path}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error loading class names: {e}")
            sys.exit(1)

    def postprocess(self, output: torch.Tensor, *args, **kwargs) -> List[Tuple[int, float]]:
        """Implementation of DataUtilsInterface.postprocess for classification."""
        return self.postprocess_imagenet(output)

    def postprocess_imagenet(self, output: torch.Tensor) -> List[Tuple[int, float]]:
        probabilities = torch.nn.functional.softmax(output[0], dim=0)
        top5_prob, top5_catid = torch.topk(probabilities, 5)
        return list(zip(top5_catid.tolist(), top5_prob.tolist()))

    def draw_predictions(self, image: Image.Image, predictions: List[Tuple[int, float]], 
                        font_size: int = 20, text_color: str = "red",
                        bg_color: str = "white", padding: int = 5) -> Image.Image:
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype(self.font_path, font_size)
            logger.debug(f"Using TrueType font from {self.font_path}")
        except IOError:
            font = ImageFont.load_default()
            logger.warning(f"Failed to load font from {self.font_path}. Using default font.")

        top_class_id, top_prob = predictions[0]
        class_name = self.class_names[top_class_id]
        text = f"{class_name}: {top_prob:.2%}"

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x = image.width - text_width - 10
        y = 10

        background = Image.new(
            "RGBA", (text_width + 2 * padding, text_height + 2 * padding), bg_color
        )
        image.paste(background, (x - padding, y - padding), background)
        draw.text((x, y), text, font=font, fill=text_color)

        return image


class DetectionUtils(DataUtilsInterface):
    def __init__(self, class_names: List[str], font_path: str,
                 conf_threshold: float = 0.25, iou_threshold: float = 0.45,
                 input_size: Tuple[int, int] = (224, 224)):
        self.class_names = class_names
        self.font_path = font_path
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.input_size = input_size

    def postprocess(self, outputs: Any, original_img_size: Optional[Tuple[int, int]] = None, 
                   *args, **kwargs) -> List[Tuple[List[int], float, int]]:
        """Implementation of DataUtilsInterface.postprocess for object detection."""
        if original_img_size is None:
            raise ValueError("original_img_size is required for detection postprocessing")
            
        import cv2 # type: ignore

        logger.info("Starting postprocessing of detection model outputs")

        if isinstance(outputs, tuple):
            outputs = outputs[0]

        outputs = outputs.detach().cpu().numpy()
        if outputs.ndim == 1:
            outputs = outputs[np.newaxis, :]
        outputs = np.transpose(np.squeeze(outputs))
        rows = outputs.shape[0]

        boxes, scores, class_ids = [], [], []
        img_w, img_h = original_img_size
        input_height, input_width = self.input_size

        x_factor = img_w / input_width
        y_factor = img_h / input_height

        for i in range(rows):
            classes_scores = outputs[i][4:]
            max_score = np.amax(classes_scores)

            if max_score >= self.conf_threshold:
                class_id = np.argmax(classes_scores)
                x, y, w, h = outputs[i][:4]
                left = int((x - w / 2) * x_factor)
                top = int((y - h / 2) * y_factor)
                width = int(w * x_factor)
                height = int(h * y_factor)
                class_ids.append(class_id)
                scores.append(max_score)
                boxes.append([left, top, width, height])

        indices = cv2.dnn.NMSBoxes(boxes, scores, self.conf_threshold, self.iou_threshold)
        detections = []

        if indices is not None and len(indices) > 0:
            indices = indices.flatten()
            for i in indices:
                detections.append((boxes[i], scores[i], class_ids[i]))

        return detections

    def draw_detections(self, image: Image.Image, detections: List[Tuple[List[int], float, int]],
                       padding: int = 2, font_size: int = 12, box_color: str = "red",
                       text_color: Tuple[int, int, int] = (255, 255, 255),
                       bg_color: Tuple[int, int, int, int] = (0, 0, 0, 128)) -> Image.Image:
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype(self.font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            logger.warning(f"Failed to load font from {self.font_path}. Using default font.")

        for box, score, class_id in detections:
            if isinstance(box, (list, tuple)) and len(box) == 4:
                x1, y1, w, h = box
                x2, y2 = x1 + w, y1 + h

                draw.rectangle([x1, y1, x2, y2], outline=box_color, width=2)
                label = f"{self.class_names[class_id]}: {score:.2f}"

                bbox = draw.textbbox((0, 0), label, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]

                label_x = max(x1 + padding, 0)
                label_y = max(y1 + padding, 0)

                background = Image.new(
                    "RGBA",
                    (text_width + 2 * padding, text_height + 2 * padding),
                    bg_color,
                )
                image.paste(background, (label_x - padding, label_y - padding), background)
                draw.text((label_x, label_y), label, fill=text_color, font=font)

        return image


def get_utils_class(experiment_type: str) -> Type[DataUtilsInterface]:
    """Returns the appropriate utility class based on experiment type."""
    if experiment_type == 'yolo':
        return DetectionUtils
    elif experiment_type in ['imagenet', 'alexnet']:
        return ClassificationUtils
    else:
        raise ValueError(f"Unsupported experiment type: {experiment_type}")