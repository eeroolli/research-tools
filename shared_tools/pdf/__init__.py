"""PDF processing utilities.

Note: some helpers depend on optional heavy dependencies (e.g. OpenCV). This
package's public imports are therefore guarded so light-weight modules can be
used in environments without those optional dependencies (e.g. during tests).
"""

__all__ = []

try:
    from .pdf_rotation_handler import PDFRotationHandler  # noqa: F401

    __all__.append("PDFRotationHandler")
except (ImportError, ModuleNotFoundError):
    # Optional dependency missing (e.g. cv2)
    pass

try:
    from .border_remover import BorderRemover  # noqa: F401

    __all__.append("BorderRemover")
except (ImportError, ModuleNotFoundError):
    pass

