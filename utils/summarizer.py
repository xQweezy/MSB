import asyncio
import logging
from transformers import T5ForConditionalGeneration, T5Tokenizer
import torch

logger = logging.getLogger(__name__)

_model = None
_tokenizer = None
_device = None

def load_model():
    global _model, _tokenizer, _device
    if _model is not None:
        return _model, _tokenizer, _device
    logger.info("🔄 Загрузка модели T5 для суммаризации...")
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_name = "cointegrated/rut5-base-absum"
    _tokenizer = T5Tokenizer.from_pretrained(model_name)
    _model = T5ForConditionalGeneration.from_pretrained(model_name)
    _model = _model.to(_device)
    _model.eval()
    logger.info("✅ Модель загружена")
    return _model, _tokenizer, _device

async def summarize_text(text: str, max_length: int = 200, min_length: int = 80) -> str:
    """
    Генерирует краткое содержание текста.
    Параметры:
        text (str): исходный текст.
        max_length (int): максимальная длина генерируемого текста (в токенах).
        min_length (int): минимальная длина генерируемого текста.
    """
    model, tokenizer, device = await asyncio.get_event_loop().run_in_executor(None, load_model)
    if len(text) > 2000:
        text = text[:2000] + "..."
    loop = asyncio.get_event_loop()

    def _generate():
        inputs = tokenizer(text, return_tensors="pt", max_length=512, truncation=True).to(device)
        with torch.no_grad():
            outputs = model.generate(
                inputs.input_ids,
                max_length=max_length,
                min_length=min_length,
                num_beams=4,
                no_repeat_ngram_size=3,
                early_stopping=True,
                do_sample=False
            )
        return tokenizer.decode(outputs[0], skip_special_tokens=True)

    summary = await loop.run_in_executor(None, _generate)
    return summary if summary else "❌ Не удалось сгенерировать краткое содержание."