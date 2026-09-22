"""
upload.py — POST /api/upload

接收文件上传，调用 DataManager.create_dataset()
返回 dataset_id + 列信息 + 字段类型 + 样本数据
"""
import logging

from flask import Blueprint, request
from werkzeug.utils import secure_filename

from api.errors import error_response, success_response
from config import UPLOAD_CONFIG
from core.data_manager import (
    DataManagerError, FileTooLargeError, InvalidFileFormatError,
    data_manager,
)

logger = logging.getLogger(__name__)

bp = Blueprint("upload", __name__, url_prefix="/api")


def _allowed_file(filename: str) -> bool:
    """检查扩展名是否允许"""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in UPLOAD_CONFIG["allowed_extensions"]


@bp.route("/upload", methods=["POST"])
def upload_file():
    """上传 CSV/Excel 文件并创建数据集"""
    if "file" not in request.files:
        return error_response("未提供文件字段 'file'", error_code="MISSING_FILE")

    file = request.files["file"]
    if not file.filename:
        return error_response("文件名为空", error_code="EMPTY_FILENAME")

    if not _allowed_file(file.filename):
        return error_response(
            f"不支持的文件格式，仅允许 {UPLOAD_CONFIG['allowed_extensions']}",
            error_code="UNSUPPORTED_FORMAT",
        )

    try:
        # 读取文件流到内存（DataManager 内部会用 secure_filename 处理）
        file_bytes = file.read()
        if not file_bytes:
            return error_response("文件为空", error_code="EMPTY_FILE")

        dataset = data_manager.upload_file(file_bytes, file.filename)

        return success_response(dataset.to_dict())

    except FileTooLargeError as e:
        return error_response(str(e), status_code=413, error_code="FILE_TOO_LARGE")
    except InvalidFileFormatError as e:
        return error_response(str(e), status_code=415, error_code="INVALID_FORMAT")
    except DataManagerError as e:
        return error_response(str(e), error_code="DATA_MANAGER_ERROR")
    except Exception as e:
        logger.exception("[Upload] 未捕获异常")
        return error_response(f"上传失败: {str(e)}", status_code=500)