import sys
import requests
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import threading
import time

from PyQt6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout, 
                             QHBoxLayout, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont

try:
    import pytesseract
    import cv2
    import numpy as np
    from pynput import mouse
    from PIL import Image, ImageGrab
    import keyboard
    HAS_ADVANCED = True
except ImportError:
    HAS_ADVANCED = False
    print("WARNING: Install pytesseract, opencv-python, pynput, keyboard, pillow")


class WorkerSignals(QObject):
    item_detected = pyqtSignal(str)
    items_loaded = pyqtSignal(dict)
    live_price_updated = pyqtSignal(str, dict)


class EFTOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.signals.item_detected.connect(self.on_item_detected)
        self.signals.items_loaded.connect(self.on_items_loaded)
        self.signals.live_price_updated.connect(self.update_live_price)
        
        self.config_file = Path("config.json")
        self.load_config()
        
        self.items_data = {}
        self.items_by_name_lower = {}
        self.items_by_uid = {}
        self.trader_prices = {}
        self.last_refresh = None
        self.items_loaded = False
        self.current_item = None
        self.current_item_name = None
        
        self.detection_active = self.config['detection']['active_on_start']
        self.last_detection_time = 0
        
        self.cache_file = Path("all_items.json")
        self.trader_data_file = Path("data.json")
        self.drag_position = None
        
        self.init_ui()
        self.load_trader_data()
        self.load_cache()
        self.start_background_refresh()
        
        if HAS_ADVANCED:
            self.setup_hotkeys()
            self.start_mouse_listener()
    
    def load_config(self):
        default = {
            "api": {
                "key": "YOUR_API_KEY_HERE",
                "url": "https://api.tarkov-market.app/api/v1",
                "refresh_interval_seconds": 300
            },
            "hotkeys": {
                "toggle_detection": "f9",
                "toggle_overlay": "f10"
            },
            "overlay": {
                "opacity": 0.95,
                "width": 250,
                "height": 150,
                "position_x": 100,
                "position_y": 100
            },
            "detection": {
                "active_on_start": True,
                "cooldown_seconds": 0.5
            }
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.config = {**default, **loaded}
            except:
                self.config = default
                self.save_config()
        else:
            self.config = default
            self.save_config()
    
    def save_config(self):
        try:
            self.config['overlay']['position_x'] = self.x()
            self.config['overlay']['position_y'] = self.y()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except:
            pass
    
    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        self.setFixedSize(self.config['overlay']['width'], self.config['overlay']['height'])
        self.setWindowOpacity(self.config['overlay']['opacity'])
        self.move(self.config['overlay']['position_x'], self.config['overlay']['position_y'])
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.setStyleSheet("""
            QWidget {
                background-color: #1a1a1a;
                color: #e0e0e0;
                font-family: Arial;
                font-size: 11px;
            }
            QLabel {
                background-color: transparent;
            }
        """)
        
        header = QFrame()
        header.setStyleSheet("background-color: #0d0d0d; padding: 2px;")
        header.setFixedHeight(20)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(4, 2, 4, 2)
        
        title = QLabel("EFT")
        title.setStyleSheet("color: #4a9eff; font-weight: bold; font-size: 10px;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        self.status_label = QLabel("O")
        self.status_label.setStyleSheet("color: #ff4444; font-size: 12px;")
        header_layout.addWidget(self.status_label)
        
        header.setLayout(header_layout)
        main_layout.addWidget(header)
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(6, 4, 6, 4)
        self.content_layout.setSpacing(0)
        self.content_widget.setLayout(self.content_layout)
        main_layout.addWidget(self.content_widget)
        
        self.setLayout(main_layout)
        self.show_waiting()
    
    def show_waiting(self):
        self.clear_content()
        color = "#00ff00" if self.detection_active else "#ff4444"
        
        ready = QLabel("READY")
        ready.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        ready.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addStretch()
        self.content_layout.addWidget(ready)
        
        hint = QLabel("Inspect items")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(hint)
        
        if self.items_loaded:
            count = QLabel(f"{len(self.items_data)} items")
            count.setStyleSheet("color: #666; font-size: 9px; margin-top: 2px;")
            count.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(count)
        
        self.content_layout.addStretch()
    
    def on_item_detected(self, item_name):
        if item_name not in self.items_data:
            return
        
        # Prevent spam detection of same item
        if item_name == self.current_item_name:
            return
        
        item = self.items_data[item_name]
        uid = item.get('uid')
        self.show_item(item_name, item)
        
        if uid:
            threading.Thread(target=self.fetch_live_price, args=(item_name, uid), daemon=True).start()
    
    def fetch_live_price(self, item_name, uid):
        try:
            url = f"{self.config['api']['url']}/item"
            params = {'uid': uid, 'x-api-key': self.config['api']['key']}
            r = requests.get(url, params=params, timeout=10)
            
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    live_item = data[0]
                    if item_name in self.items_data:
                        self.items_data[item_name].update(live_item)
                        self.update_cache_file()
                    self.signals.live_price_updated.emit(item_name, live_item)
                    print(f"Live price updated: {item_name}")
        except Exception as e:
            print(f"Live price error: {e}")
    
    def update_cache_file(self):
        try:
            items_list = list(self.items_data.values())
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(items_list, f, indent=2)
        except:
            pass
    
    def update_live_price(self, item_name, live_item):
        if self.current_item_name == item_name:
            self.show_item(item_name, live_item)
    
    def show_item(self, item_name, item):
        self.current_item_name = item_name
        bsg_id = item.get('bsgId') or item.get('uid')
        self.clear_content()
        
        display_name = item_name if len(item_name) <= 28 else item_name[:28] + "..."
        
        name = QLabel(display_name)
        name.setStyleSheet("color: #fff; font-size: 11px; font-weight: bold;")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(name)
        
        trader_name = item.get('traderName', 'Unknown')
        trader_price_cur = item.get('traderPriceCur', 'RUB')
        
        trader_price = self.trader_prices.get(bsg_id, item.get('traderPrice', 0)) if bsg_id else item.get('traderPrice', 0)
        banned = item.get('bannedOnFlea', False)
        
        self.add_compact_row("Trader", trader_name, "#4a9eff", 11)
        self.add_compact_row("Trade Price", f"{trader_price:,} {trader_price_cur}", "#ccc", 12)
        
        if not banned:
            flea_price = item.get('price', 0)
            self.add_compact_row("Flea Price", f"{flea_price:,} RUB", "#ffd700", 13)
            
            avg24h = item.get('avg24hPrice', 0)
            diff24h = item.get('diff24h', 0)
            color24 = "#0f0" if diff24h >= 0 else "#f44"
            sign24 = "+" if diff24h >= 0 else ""
            self.add_compact_row("24h Avg", f"{avg24h:,} RUB ({sign24}{diff24h:.1f}%)", color24, 11)
            
            avg7d = item.get('avg7daysPrice', 0)
            diff7d = item.get('diff7days', 0)
            color7d = "#0f0" if diff7d >= 0 else "#f44"
            sign7d = "+" if diff7d >= 0 else ""
            self.add_compact_row("7d Avg", f"{avg7d:,} RUB ({sign7d}{diff7d:.1f}%)", color7d, 11)
            
            profit = flea_price - trader_price
            if profit > 0:
                profit_text = f"+{profit:,} RUB (flea)"
                profit_color = "#0f0"
            elif profit < 0:
                profit_text = f"{abs(profit):,} RUB (trader)"
                profit_color = "#f44"
            else:
                profit_text = "0 RUB"
                profit_color = "#888"
            
            self.add_compact_row("Profit", profit_text, profit_color, 12)
            
            updated = item.get('updated', '')
            if updated:
                ago = self.time_ago_gmt8(updated)
                time_label = QLabel(ago)
                time_label.setStyleSheet("color: #666; font-size: 9px; margin-top: 2px;")
                time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.content_layout.addWidget(time_label)
        else:
            banned_label = QLabel("BANNED ON FLEA")
            banned_label.setStyleSheet("color: #f44; font-weight: bold; font-size: 11px; margin-top: 6px;")
            banned_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(banned_label)
        
        self.content_layout.addStretch()
    
    def add_compact_row(self, label, value, color="#fff", value_size=11):
        row = QWidget()
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 1, 0, 1)
        row_layout.setSpacing(4)
        
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #888; font-size: 10px;")
        lbl.setFixedWidth(55)
        row_layout.addWidget(lbl)
        row_layout.addStretch()
        
        val = QLabel(value)
        val.setStyleSheet(f"color: {color}; font-size: {value_size}px; font-weight: bold;")
        val.setAlignment(Qt.AlignmentFlag.AlignRight)
        row_layout.addWidget(val)
        
        row.setLayout(row_layout)
        self.content_layout.addWidget(row)
    
    def time_ago_gmt8(self, timestamp):
        try:
            if timestamp.endswith('Z'):
                timestamp = timestamp[:-1] + '+00:00'
            
            dt = datetime.fromisoformat(timestamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            gmt8 = timezone(timedelta(hours=8))
            dt_gmt8 = dt.astimezone(gmt8)
            now_gmt8 = datetime.now(gmt8)
            diff = now_gmt8 - dt_gmt8
            total_seconds = int(diff.total_seconds())
            
            if total_seconds < 60:
                return "just now"
            elif total_seconds < 3600:
                return f"{total_seconds // 60}m ago"
            elif total_seconds < 86400:
                return f"{total_seconds // 3600}h ago"
            else:
                return f"{total_seconds // 86400}d ago"
        except:
            return "?"
    
    def clear_content(self):
        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
            self.save_config()
    
    def setup_hotkeys(self):
        try:
            keyboard.add_hotkey(self.config['hotkeys']['toggle_detection'], self.toggle_detection)
            keyboard.add_hotkey(self.config['hotkeys']['toggle_overlay'], self.toggle_overlay)
            print("Hotkeys: F9=Toggle, F10=Hide")
        except Exception as e:
            print(f"Hotkey error: {e}")
    
    def toggle_detection(self):
        self.detection_active = not self.detection_active
        color = "#0f0" if self.detection_active else "#f44"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        print(f"Detection: {'ON' if self.detection_active else 'OFF'}")
        if not self.detection_active:
            self.show_waiting()
    
    def toggle_overlay(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
    
    def start_background_refresh(self):
        def refresh():
            self.fetch_items()
            threading.Timer(self.config['api']['refresh_interval_seconds'], refresh).start()
        threading.Thread(target=refresh, daemon=True).start()
    
    def fetch_items(self):
        try:
            print("Fetching items...")
            url = f"{self.config['api']['url']}/items/all/download"
            params = {'x-api-key': self.config['api']['key']}
            r = requests.get(url, params=params, timeout=60)
            
            if r.status_code == 200:
                items = r.json()
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(items, f, indent=2)
                self.process_items(items)
                print(f"Loaded {len(items)} items")
        except Exception as e:
            print(f"Fetch error: {e}")
    
    def process_items(self, items):
        temp_data = {}
        temp_lower = {}
        temp_uid = {}
        
        for item in items:
            name = item.get('name') or item.get('shortName')
            uid = item.get('uid') or item.get('bsgId')
            if name and uid:
                temp_data[name] = item
                temp_lower[name.lower()] = name
                temp_uid[uid] = item
                
                name_clean = name.lower().replace('-', ' ').replace('_', ' ')
                if name_clean not in temp_lower:
                    temp_lower[name_clean] = name
        
        self.signals.items_loaded.emit({'data': temp_data, 'lower': temp_lower, 'uid': temp_uid})
    
    def on_items_loaded(self, items_dict):
        self.items_data = items_dict['data']
        self.items_by_name_lower = items_dict['lower']
        self.items_by_uid = items_dict['uid']
        self.items_loaded = True
        self.last_refresh = datetime.now(timezone.utc)
        print(f"Items ready: {len(self.items_data)}")
        self.show_waiting()
    
    def load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    items = json.load(f)
                    self.process_items(items)
                print(f"Loaded cache: {len(items)} items")
            except Exception as e:
                print(f"Cache error: {e}")
    
    def load_trader_data(self):
        if not self.trader_data_file.exists():
            print("data.json not found")
            return
        
        try:
            with open(self.trader_data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            items = data.get('items', []) if isinstance(data, dict) else data
            
            for item in items:
                bsg_id = item.get('bsgID')
                price = item.get('price', 0)
                if bsg_id and price:
                    self.trader_prices[bsg_id] = price
            
            print(f"Loaded trader prices: {len(self.trader_prices)} items")
        except Exception as e:
            print(f"Trader data error: {e}")
    
    def start_mouse_listener(self):
        def on_move(x, y):
            if not self.detection_active or not self.items_loaded:
                return
            
            t = time.time()
            if t - self.last_detection_time < self.config['detection']['cooldown_seconds']:
                return
            
            self.last_detection_time = t
            threading.Thread(target=self.detect_item, daemon=True).start()
        
        try:
            listener = mouse.Listener(on_move=on_move)
            listener.daemon = True
            listener.start()
            print("Mouse detection: ACTIVE")
        except Exception as e:
            print(f"Mouse detection failed: {e}")
    
    def detect_item(self):
        if not HAS_ADVANCED:
            return
        
        try:
            from pynput.mouse import Controller
            mc = Controller()
            x, y = mc.position
            
            w, h = 600, 400  # Smaller capture area for better performance
            bbox = (x - w//2, y - h//2, x + w//2, y + h//2)
            screenshot = ImageGrab.grab(bbox=bbox)
            
            img = np.array(screenshot)
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            
            # Reduced preprocessing for speed
            methods = [
                cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
                cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]
            ]
            
            all_text = []
            
            # Only use fastest PSM modes
            for method in methods:
                for psm in [6, 11]:  # Reduced from 4 modes to 2
                    try:
                        config = f'--psm {psm} --oem 3'
                        text = pytesseract.image_to_string(method, config=config)
                        all_text.append(text)
                    except:
                        continue
            
            combined = '\n'.join(all_text)
            
            lines = []
            for line in combined.split('\n'):
                line = line.strip()
                line = line.replace('|', 'I').replace('0', 'O').replace('1', 'l')
                line = ' '.join(line.split())
                if len(line) >= 3:
                    lines.append(line)
            
            lines = list(set(lines))
            
            # EXACT MATCH - fastest
            for line in lines:
                line_lower = line.lower()
                if line_lower in self.items_by_name_lower:
                    name = self.items_by_name_lower[line_lower]
                    if name != self.current_item:
                        self.current_item = name
                        self.signals.item_detected.emit(name)
                        return
            
            # SUBSTRING MATCH
            for line in lines:
                line_lower = line.lower().strip()
                if len(line_lower) < 4:
                    continue
                
                for item_lower, item_name in self.items_by_name_lower.items():
                    if len(item_lower) < 4:
                        continue
                    
                    if line_lower in item_lower or item_lower in line_lower:
                        overlap = min(len(line_lower), len(item_lower))
                        ratio = overlap / max(len(line_lower), len(item_lower))
                        
                        if ratio > 0.4:
                            if item_name != self.current_item:
                                self.current_item = item_name
                                self.signals.item_detected.emit(item_name)
                                return
            
            # FUZZY WORD MATCH
            for line in lines:
                line_lower = line.lower()
                line_words = set(line_lower.split())
                
                if len(line_words) < 2:
                    continue
                
                for item_lower, item_name in self.items_by_name_lower.items():
                    item_words = set(item_lower.split())
                    
                    if len(item_words) < 2:
                        continue
                    
                    matching_words = line_words & item_words
                    
                    if len(matching_words) >= 2:
                        match_ratio = len(matching_words) / len(item_words)
                        
                        if match_ratio > 0.5:
                            if item_name != self.current_item:
                                self.current_item = item_name
                                self.signals.item_detected.emit(item_name)
                                return
        except Exception as e:
            pass


def main():
    app = QApplication(sys.argv)
    
    print("=" * 50)
    print("EFT PRICE CHECKER")
    print("=" * 50)
    
    overlay = EFTOverlay()
    overlay.show()
    
    print("\nHotkeys: F9=Toggle Detection, F10=Hide")
    print("=" * 50)
    
    sys.exit(app.exec())


if __name__ == "__main__":

    main()

