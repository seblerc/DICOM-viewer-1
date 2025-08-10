import sys, os
import numpy as np
import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut
from PyQt5 import QtCore, QtGui, QtWidgets
from pydicom.pixel_data_handlers.util import apply_voi_lut, apply_modality_lut


def to_uint8(pixel_array, photometric, wc=None, ww=None):
    arr = pixel_array.astype(np.float32)

    
    if wc is None or ww is None:
        lo, hi = np.percentile(arr, 1), np.percentile(arr, 99)
        wc = float((lo + hi) / 2.0)
        ww = float(max(hi - lo, 1.0))

    lo, hi = wc - ww/2.0, wc + ww/2.0
    arr = np.clip((arr - lo) / (hi - lo), 0, 1)
    img = (arr * 255).astype(np.uint8)

    if str(photometric).upper() == "MONOCHROME1":
        img = 255 - img
    return img

def ds_to_qimage(ds, frame_index=0, wc=None, ww=None):
    
    if hasattr(ds, "NumberOfFrames") and int(getattr(ds, "NumberOfFrames", 1)) > 1:
        arr = ds.pixel_array[int(frame_index)]
    else:
        arr = ds.pixel_array

    
    if int(getattr(ds, "SamplesPerPixel", 1)) == 3:
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        arr = np.ascontiguousarray(arr)
        h, w, _ = arr.shape
        qimg = QtGui.QImage(arr.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
        return qimg.copy()

    
    arr = apply_modality_lut(arr, ds).astype(np.float32)

    
    if wc is not None and ww is not None:
        lo, hi = wc - ww / 2.0, wc + ww / 2.0
        arr = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    else:
        
        used_voi = False
        try:
            arr = apply_voi_lut(arr, ds).astype(np.float32)
            used_voi = True
        except Exception:
            used_voi = False

        if used_voi:
            
            a_min, a_max = float(np.min(arr)), float(np.max(arr))
            arr = (arr - a_min) / (a_max - a_min) if a_max > a_min else np.zeros_like(arr, dtype=np.float32)
        else:
            
            lo, hi = np.percentile(arr, 1), np.percentile(arr, 99)
            arr = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)

    
    if str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")).upper() == "MONOCHROME1":
        arr = 1.0 - arr

    
    img8 = (arr * 255.0).astype(np.uint8)
    h, w = img8.shape
    img8 = np.ascontiguousarray(img8)
    qimg = QtGui.QImage(img8.data, w, h, w, QtGui.QImage.Format_Grayscale8)
    return qimg.copy()
    

    


class ImageView(QtWidgets.QGraphicsView):
    zoomChanged = QtCore.pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.pix = QtWidgets.QGraphicsPixmapItem()
        self.scene().addItem(self.pix)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(25, 25, 25)))
        self.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self._scale = 1.0

    def set_image(self, qimg):
        self.pix.setPixmap(QtGui.QPixmap.fromImage(qimg))
        self.fitInView(self.pix, QtCore.Qt.KeepAspectRatio)
        self._scale = 1.0
        self.zoomChanged.emit(self._scale)

    def wheelEvent(self, e: QtGui.QWheelEvent):
        if self.pix.pixmap().isNull(): return
        factor = 1.25 if e.angleDelta().y() > 0 else 1/1.25
        self.scale(factor, factor)
        self._scale *= factor
        self.zoomChanged.emit(self._scale)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Basit DICOM Viewer (PyQt5)")
        self.resize(1200, 750)

        self.ds = None
        self.frame_index = 0
        self.wc = None
        self.ww = None

        
        self.view = ImageView()

        
        self.meta = QtWidgets.QPlainTextEdit(); self.meta.setReadOnly(True)
        self.meta.setStyleSheet("background:#101010;color:#ddd;font-family:Consolas,monospace;")

        self.btn_open = QtWidgets.QPushButton("DICOM Aç")
        self.btn_fit  = QtWidgets.QPushButton("Sığdır")
        self.btn_reset= QtWidgets.QPushButton("Reset W/L")

        self.slider_frame = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.slider_frame.setEnabled(False)
        self.lbl_frame = QtWidgets.QLabel("Frame: -")

        self.slider_wc = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.slider_wc.setEnabled(False)
        self.slider_ww = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.slider_ww.setEnabled(False)


        self.slider_wc.setMinimum(-600)
        self.slider_wc.setMaximum(600)
        self.slider_wc.setSingleStep(1)


        self.slider_ww.setMinimum(1)
        self.slider_ww.setMaximum(3000)
        self.slider_ww.setSingleStep(1)

        self.lbl_wc = QtWidgets.QLabel("WC: -")
        self.lbl_ww = QtWidgets.QLabel("WW: -")
        self.lbl_zoom = QtWidgets.QLabel("Zoom: 100%")

        
        right = QtWidgets.QWidget()
        rlay = QtWidgets.QVBoxLayout(right); rlay.setContentsMargins(8,8,8,8)
        rlay.addWidget(QtWidgets.QLabel("Metadata"))
        rlay.addWidget(self.meta, 1)
        box = QtWidgets.QGroupBox("Kontroller")
        form = QtWidgets.QFormLayout(box)
        form.addRow(self.btn_open)
        form.addRow(self.btn_fit)
        form.addRow(self.btn_reset)
        form.addRow(self.lbl_frame); form.addRow(self.slider_frame)
        form.addRow(self.lbl_wc); form.addRow(self.slider_wc)
        form.addRow(self.lbl_ww); form.addRow(self.slider_ww)
        form.addRow(self.lbl_zoom)
        rlay.addWidget(box, 0)

        central = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(central); hl.setContentsMargins(6,6,6,6); hl.setSpacing(6)
        hl.addWidget(self.view, 1)
        hl.addWidget(right, 0)
        self.setCentralWidget(central)

       
        self.btn_open.clicked.connect(self.open_dcm)
        self.btn_fit.clicked.connect(lambda: self.view.fitInView(self.view.pix, QtCore.Qt.KeepAspectRatio))
        self.btn_reset.clicked.connect(self.reset_window)
        self.slider_frame.valueChanged.connect(self.on_frame_change)
        self.slider_wc.valueChanged.connect(self.on_window_change)
        self.slider_ww.valueChanged.connect(self.on_window_change)
        self.view.zoomChanged.connect(self.on_zoom)

    
    def open_dcm(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "DICOM Seç", "", "DICOM (*.dcm);;All (*.*)")
        if not path: return
        try:
            ds = pydicom.dcmread(path)
            
            _ = ds.pixel_array  
            self.ds = ds
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Hata", f"Dosya okunamadı:\n{e}")
            return

        
        self.show_meta(ds)

        
        self.wc = getattr(ds, "WindowCenter", None)
        self.ww = getattr(ds, "WindowWidth", None)
        if isinstance(self.wc, pydicom.multival.MultiValue): self.wc = float(self.wc[0])
        if isinstance(self.ww, pydicom.multival.MultiValue): self.ww = float(self.ww[0])

        self.slider_wc.setEnabled(True); self.slider_ww.setEnabled(True)
        if self.wc is None or self.ww is None:
            self.slider_wc.setValue(0); self.slider_ww.setValue(1000)
        else:
            self.slider_wc.setValue(int(self.wc))
            self.slider_ww.setValue(int(self.ww))

        
        n_frames = int(getattr(self.ds, "NumberOfFrames", 1))
        self.slider_frame.setEnabled(n_frames > 1)
        self.slider_frame.setMinimum(1); self.slider_frame.setMaximum(n_frames)
        self.frame_index = 0
        self.lbl_frame.setText(f"Frame: 1/{n_frames}")

        
        self.update_image()

    def show_meta(self, ds):
        lines = []
        def g(tag, name):
            val = getattr(ds, name, None)
            return f"{name}: {val}" if val is not None else None
        wanted = [
            "PatientName","PatientID","StudyDate","Modality",
            "StudyInstanceUID","SeriesInstanceUID","SOPInstanceUID",
            "PhotometricInterpretation","PixelSpacing","Rows","Columns",
            "BitsStored","SamplesPerPixel","NumberOfFrames","TransferSyntaxUID",
            "WindowCenter","WindowWidth"
        ]
        for name in wanted:
            s = g(None, name)
            if s: lines.append(s)
        self.meta.setPlainText("\n".join(lines))

    
    def update_image(self):
        if self.ds is None: return
        qimg = ds_to_qimage(self.ds, self.frame_index, self.wc, self.ww)
        self.view.set_image(qimg)
        self.lbl_wc.setText(f"WC: {self.wc if self.wc is not None else '-'}")
        self.lbl_ww.setText(f"WW: {self.ww if self.ww is not None else '-'}")

    
    def on_frame_change(self, v):
        self.frame_index = v - 1
        total = int(getattr(self.ds, "NumberOfFrames", 1))
        self.lbl_frame.setText(f"Frame: {v}/{total}")
        self.update_image()

    def on_window_change(self, _):
        self.wc = float(self.slider_wc.value())
        self.ww = float(max(self.slider_ww.value(), 1))
        self.update_image()

    def reset_window(self):
        self.wc, self.ww = None, None
        self.update_image()

    def on_zoom(self, scale):
        self.lbl_zoom.setText(f"Zoom: {int(scale*100)}%")


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
