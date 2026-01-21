# -*- coding: utf-8 -*-
"""
局域网文件共享与远程关机控制工具
功能：
  - 浏览/下载/预览文件（支持文本、图片、音视频）
  - 手机端友好界面（响应式设计）
  - 远程安排关机 / 取消关机（通过前端按钮或创建指令文件）
  - 新建 .txt 文件、新建目录、上传文件
  - 支持 HTTP Range 分段请求（用于视频/音频拖动播放）
  - 自动处理客户端断开连接（避免命令行报错）
  - 多文件夹共享支持（通过GUI添加多个共享目录）
  - 保存/加载共享文件夹配置
  - 电脑端和手机端互发文本消息

作者：基于 Qwen 辅助开发，用户自行整合修改
"""

import os
import sys
import json
import socket
import urllib.parse
import threading
import time
import subprocess
import glob
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import mimetypes
import re

# ==============================
# PySide6 GUI 相关导入
# ==============================
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QListWidget, QPushButton, QLabel, 
                               QMessageBox, QTextEdit, QDialog, QHBoxLayout as QHBox,
                               QVBoxLayout as QVBox)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QClipboard

# ==============================
# 全局配置
# ==============================

# 支持在网页中直接预览（而非强制下载）的文件扩展名集合
PREVIEW_EXTENSIONS = {
    # 文本类
    '.txt', '.log', '.py', '.js', '.css', '.html', '.htm', '.json', '.xml', '.md', '.ini', '.cfg', '.yml', '.yaml',
    # 图片类
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg',
    # 音频类
    '.mp3', '.wav', '.ogg', '.aac',
    # 视频类
    '.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv'
}

# ==============================
# 全局状态变量（用于前端显示关机状态）
# ==============================

# 当前关机状态提示字符串（如"电脑端将于600秒后关机"）
shutdown_status = ""
# 用于保护 shutdown_status 的线程锁
shutdown_lock = threading.Lock()

# ==============================
# 全局共享目录列表
# ==============================
shared_dirs = []
shared_dirs_lock = threading.Lock()

# ==============================
# 全局文本消息队列
# ==============================
text_messages = []  # 存储待处理的文本消息
text_messages_lock = threading.Lock()

# ==============================
# 配置文件路径
# ==============================
CONFIG_FILE = "shared_folders.json"

def save_shared_folders_config(folders):
    """保存共享文件夹配置到文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(folders, f, ensure_ascii=False, indent=2)
        print(f"已保存 {len(folders)} 个共享文件夹配置到 {CONFIG_FILE}")
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False

def load_shared_folders_config():
    """从文件加载共享文件夹配置"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                folders = json.load(f)
            print(f"从 {CONFIG_FILE} 加载了 {len(folders)} 个共享文件夹配置")
            return folders
        else:
            print(f"配置文件 {CONFIG_FILE} 不存在，将创建新配置")
            return []
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return []

        
# ==============================
# 端口配置文件路径
# ==============================
PORT_CONFIG_FILE = "port_config.json"

def save_port_config(port):
    """保存端口配置到文件"""
    try:
        with open(PORT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({"port": port}, f, ensure_ascii=False, indent=2)
        print(f"已保存端口配置: {port}")
        return True
    except Exception as e:
        print(f"保存端口配置失败: {e}")
        return False

def load_port_config():
    """从文件加载端口配置"""
    try:
        if os.path.exists(PORT_CONFIG_FILE):
            with open(PORT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            port = config.get("port", 20261)  # 默认20261
            print(f"从 {PORT_CONFIG_FILE} 加载端口配置: {port}")
            return port
        else:
            print(f"端口配置文件 {PORT_CONFIG_FILE} 不存在，使用默认端口20261")
            return 20261
    except Exception as e:
        print(f"加载端口配置失败: {e}")
        return 20261        

# ==============================
# GUI 对话框类 - 端口设置
# ==============================
class PortConfigDialog(QDialog):
    def __init__(self, current_port, parent=None):
        super().__init__(parent)
        self.current_port = current_port
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('端口设置')
        self.setGeometry(450, 350, 400, 200)
        
        layout = QVBoxLayout()
        
        # 提示标签
        label = QLabel('请输入HTTP端口号 (80-65535):')
        layout.addWidget(label)
        
        # 端口输入框
        self.port_input = QTextEdit()
        self.port_input.setMaximumHeight(40)
        self.port_input.setPlainText(str(self.current_port))
        self.port_input.setPlaceholderText("例如：20261")
        layout.addWidget(self.port_input)
        
        # 验证提示
        self.validation_label = QLabel('')
        self.validation_label.setStyleSheet("color: red;")
        layout.addWidget(self.validation_label)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 取消按钮
        self.cancel_btn = QPushButton('取消')
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        # 确认按钮
        self.confirm_btn = QPushButton('确认')
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.confirm_btn.clicked.connect(self.validate_and_accept)
        button_layout.addWidget(self.confirm_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def validate_and_accept(self):
        port_text = self.port_input.toPlainText().strip()
        
        if not port_text.isdigit():
            self.validation_label.setText("请输入数字！")
            return
        
        port = int(port_text)
        
        if port < 80 or port > 65535:
            self.validation_label.setText("端口范围必须在80-65535之间！")
            return
        
        self.port = port
        self.accept()
    
    def get_port(self):
        return self.port

        
# ==============================
# GUI 对话框类 - 发送文本
# ==============================
class SendTextDialog(QDialog):
    def __init__(self, parent=None, is_mobile=False):
        super().__init__(parent)
        self.is_mobile = is_mobile
        self.initUI()
        
    def initUI(self):
        title = "发送文本到手机端" if not self.is_mobile else "发送文本到电脑端"
        self.setWindowTitle(title)
        self.setGeometry(400, 300, 500, 400)
        
        layout = QVBoxLayout()
        
        # 提示标签
        label = QLabel(f"请输入要发送的文本内容：")
        layout.addWidget(label)
        
        # 多行文本框
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("在这里输入文本内容...")
        layout.addWidget(self.text_edit)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 剪贴板按钮
        self.clipboard_btn = QPushButton('剪贴板')
        self.clipboard_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.clipboard_btn.clicked.connect(self.paste_from_clipboard)
        button_layout.addWidget(self.clipboard_btn)
        
        # 取消按钮
        self.cancel_btn = QPushButton('取消')
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        # 确认按钮
        self.confirm_btn = QPushButton('确认')
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.confirm_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.confirm_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.text_edit.setPlainText(text)
    
    def get_text(self):
        return self.text_edit.toPlainText()

# ==============================
# GUI 对话框类 - 接收文本
# ==============================
class ReceiveTextDialog(QDialog):
    def __init__(self, message, sender_ip, is_mobile=False, parent=None):
        super().__init__(parent)
        self.message = message
        self.sender_ip = sender_ip
        self.is_mobile = is_mobile
        self.initUI()
        
    def initUI(self):
        if self.is_mobile:
            title = f"电脑端消息 - {self.sender_ip}"
            sender_type = "电脑端"
        else:
            title = f"手机端消息 - {self.sender_ip}"
            sender_type = "手机端"
            
        self.setWindowTitle(title)
        self.setGeometry(400, 300, 500, 400)
        
        layout = QVBoxLayout()
        
        # 提示标签
        label_text = f"{sender_type} IP: {self.sender_ip} 给你发送文本消息："
        label = QLabel(label_text)
        layout.addWidget(label)
        
        # 多行文本框（只读）
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.message)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 复制按钮
        self.copy_btn = QPushButton('复制')
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
        """)
        self.copy_btn.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(self.copy_btn)
        
        # 取消按钮
        self.cancel_btn = QPushButton('关闭')
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 5px;
                margin: 5px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.message)
        QMessageBox.information(self, "复制成功", "文本已复制到剪贴板")


        
# ==============================
# GUI 窗口类
# ==============================
class FolderShareWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 首先加载端口配置
        self.current_port = load_port_config()  # 先加载端口配置
        
        # 然后初始化UI
        self.initUI()
        
        self.shared_paths = []  # 存储用户选择的文件夹路径
        self.load_config()      # 加载上次的配置
        
        # 启动消息检查定时器
        self.message_timer = QTimer()
        self.message_timer.timeout.connect(self.check_messages)
        self.message_timer.start(1000)  # 每秒检查一次
        
    def initUI(self):
        self.setWindowTitle('局域网文件夹共享 - 选择多个文件夹')
        self.setGeometry(300, 300, 700, 450)  # 稍微增大窗口宽度以容纳更多按钮
        
        # 中央窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        layout = QVBoxLayout()
        
        # 提示标签
        label = QLabel('拖拽文件夹到此窗口，或点击共享按钮开始服务')
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("""
            font-size: 14px;
            color: #333;
            padding: 10px;
            background-color: #f0f0f0;
            border-radius: 5px;
            margin: 10px;
        """)
        layout.addWidget(label)
        
        # 列表框，显示已添加的文件夹
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        layout.addWidget(self.list_widget)
        
        # 按钮布局 - 第一行（4个按钮）
        button_layout1 = QHBoxLayout()
        
        # 共享按钮
        self.share_btn = QPushButton('共享')
        self.share_btn.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 8px 14px;
            font-size: 12px;
            border-radius: 5px;
            margin: 5px;
            min-width: 50px;
        """)
        self.share_btn.clicked.connect(self.start_sharing)
        button_layout1.addWidget(self.share_btn)
        
        # 删除按钮
        self.delete_btn = QPushButton('删除')
        self.delete_btn.setStyleSheet("""
            background-color: #f44336;
            color: white;
            border: none;
            padding: 8px 14px;
            font-size: 12px;
            border-radius: 5px;
            margin: 5px;
            min-width: 50px;
        """)
        self.delete_btn.clicked.connect(self.delete_selected)
        button_layout1.addWidget(self.delete_btn)
        
        # 清空按钮
        self.clear_btn = QPushButton('清空')
        self.clear_btn.setStyleSheet("""
            background-color: #2196F3;
            color: white;
            border: none;
            padding: 8px 14px;
            font-size: 12px;
            border-radius: 5px;
            margin: 5px;
            min-width: 50px;
        """)
        self.clear_btn.clicked.connect(self.clear_all)
        button_layout1.addWidget(self.clear_btn)
        
        # 端口按钮 - 新增
        self.port_btn = QPushButton('端口')
        self.port_btn.setStyleSheet("""
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 8px 14px;
            font-size: 12px;
            border-radius: 5px;
            margin: 5px;
            min-width: 50px;
        """)
        self.port_btn.clicked.connect(self.show_port_config_dialog)
        button_layout1.addWidget(self.port_btn)
        
        # 发送文本按钮
        self.send_text_btn = QPushButton('发送文本')
        self.send_text_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFC107;
                color: black;
                border: none;
                padding: 8px 16px;
                font-size: 13px;
                border-radius: 5px;
                margin: 5px;
                min-width: 50px;
            }
            QPushButton:hover {
                background-color: #FFA000;
            }
        """)
        self.send_text_btn.clicked.connect(self.show_send_text_dialog)
        button_layout1.addWidget(self.send_text_btn)
        
        layout.addLayout(button_layout1)
        

        # 状态标签
        self.status_label = QLabel(f'当前端口: {self.current_port} - 等待添加文件夹...')
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        central_widget.setLayout(layout)
        
        # 启用拖拽功能
        self.setAcceptDrops(True)
        
    def show_port_config_dialog(self):
        """显示端口配置对话框"""
        dialog = PortConfigDialog(self.current_port, self)
        if dialog.exec() == QDialog.Accepted:
            new_port = dialog.get_port()
            if new_port != self.current_port:
                self.current_port = new_port
                # 保存端口配置
                save_port_config(new_port)
                self.status_label.setText(f'端口已设置为: {new_port} - 需要重启服务生效')
                
                # 如果服务正在运行，提示需要重启
                if not self.share_btn.isEnabled():
                    QMessageBox.information(self, '端口已更改', 
                        f'端口已更改为 {new_port}，需要停止当前服务后重新启动才能生效。')
  
    def load_config(self):
        """加载上次保存的共享文件夹配置"""
        try:
            folders = load_shared_folders_config()
            for path in folders:
                if os.path.isdir(path) and path not in self.shared_paths:
                    self.shared_paths.append(path)
                    # 直接显示完整路径
                    self.list_widget.addItem(path)
            
            if self.shared_paths:
                self.status_label.setText(f'已加载 {len(self.shared_paths)} 个上次共享的文件夹')
            else:
                self.status_label.setText('等待添加文件夹...')
        except Exception as e:
            print(f"加载配置失败: {e}")
            self.status_label.setText('配置加载失败，请手动添加文件夹')
    
    def save_config(self):
        """保存当前共享文件夹配置"""
        try:
            if save_shared_folders_config(self.shared_paths):
                self.status_label.setText(f'已保存 {len(self.shared_paths)} 个文件夹配置')
            else:
                self.status_label.setText('保存配置失败')
        except Exception as e:
            print(f"保存配置失败: {e}")
            self.status_label.setText('保存配置失败')
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()
    
    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isdir(path):
                if path not in self.shared_paths:
                    self.shared_paths.append(path)
                    # 直接显示完整路径
                    self.list_widget.addItem(path)
                    self.status_label.setText(f'已添加文件夹: {os.path.basename(path)}')
                else:
                    self.status_label.setText(f'文件夹已存在: {os.path.basename(path)}')
            else:
                self.status_label.setText(f'不是有效的文件夹: {path}')
    
    def delete_selected(self):
        current_row = self.list_widget.currentRow()
        if current_row >= 0 and current_row < len(self.shared_paths):
            removed_path = self.shared_paths.pop(current_row)
            self.list_widget.takeItem(current_row)
            self.status_label.setText(f'已删除: {os.path.basename(removed_path)}')
            # 删除后自动保存配置
            self.save_config()
    
    def clear_all(self):
        if self.shared_paths:
            self.shared_paths.clear()
            self.list_widget.clear()
            self.status_label.setText('已清空所有文件夹')
            # 清空后自动保存配置
            self.save_config()
    
    def show_send_text_dialog(self):
        """显示发送文本对话框"""
        dialog = SendTextDialog(self, is_mobile=False)
        if dialog.exec() == QDialog.Accepted:
            text = dialog.get_text()
            if text.strip():
                # 保存消息到文件，供HTTP服务器读取
                self.save_text_message(text, "computer")
                self.status_label.setText("文本已准备发送，等待手机端接收...")
    
    def save_text_message(self, text, sender_type):
        """保存文本消息到文件"""
        try:
            message_data = {
                "text": text,
                "sender_type": sender_type,
                "timestamp": time.time(),
                "sender_ip": get_local_ip()
            }
            
            # 保存到消息文件
            with open("text_message.json", "w", encoding="utf-8") as f:
                json.dump(message_data, f, ensure_ascii=False, indent=2)
            print(f"文本消息已保存到文件: {len(text)} 字符")
        except Exception as e:
            print(f"保存文本消息失败: {e}")
    
    def check_messages(self):
        """检查是否有新消息"""
        try:
            if os.path.exists("mobile_text_message.json"):
                with open("mobile_text_message.json", "r", encoding="utf-8") as f:
                    message_data = json.load(f)
                
                # 显示接收对话框
                self.show_receive_dialog(message_data)
                
                # 删除消息文件
                os.remove("mobile_text_message.json")
        except Exception as e:
            pass  # 文件不存在或其他错误，忽略
    
    def show_receive_dialog(self, message_data):
        """显示接收文本对话框"""
        text = message_data.get("text", "")
        sender_ip = message_data.get("sender_ip", "未知IP")
        
        dialog = ReceiveTextDialog(text, sender_ip, is_mobile=True, parent=self)
        dialog.exec()
    
    def start_sharing(self):
        if not self.shared_paths:
            QMessageBox.warning(self, '警告', '请先添加至少一个文件夹！')
            return
        
        # 检查文件夹是否存在
        valid_paths = []
        invalid_paths = []
        
        for path in self.shared_paths:
            if os.path.exists(path) and os.path.isdir(path):
                valid_paths.append(path)
            else:
                invalid_paths.append(path)
        
        if invalid_paths:
            # 提示用户哪些路径无效
            invalid_list = '\n'.join([f'  • {path}' for path in invalid_paths])
            reply = QMessageBox.question(self, '路径无效', 
                f'以下文件夹不存在或无效:\n{invalid_list}\n\n是否从列表中移除这些无效路径并继续共享？',
                QMessageBox.Yes | QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                # 从列表中移除无效路径
                for path in invalid_paths:
                    if path in self.shared_paths:
                        self.shared_paths.remove(path)
                # 更新列表框
                self.update_list_widget()
                # 保存更新后的配置
                self.save_config()
            else:
                return
        
        if not valid_paths:
            QMessageBox.warning(self, '警告', '没有有效的文件夹可共享！')
            return
        
        # 保存配置
        self.save_config()
        
        # 更新全局共享目录列表
        global shared_dirs
        with shared_dirs_lock:
            shared_dirs.clear()
            shared_dirs.extend(valid_paths)
        
        self.status_label.setText(f'开始共享 {len(valid_paths)} 个文件夹，端口: {self.current_port}...')
        self.share_btn.setEnabled(False)
        
        # 启动HTTP服务器线程，传递当前端口
        self.server_thread = ServerThread(valid_paths, self.current_port)
        self.server_thread.server_ready.connect(self.on_server_ready)
        self.server_thread.server_error.connect(self.on_server_error)
        self.server_thread.start()
    
    def update_list_widget(self):
        """更新列表框显示"""
        self.list_widget.clear()
        for path in self.shared_paths:
            # 直接显示完整路径
            self.list_widget.addItem(path)
    
    def on_server_ready(self, ip_address, port):
        # 更新状态标签显示端口信息
        self.status_label.setText(f'服务器已启动: http://{ip_address}:{port}')
        
        # 显示访问信息
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle('服务器已启动')
        
        if len(self.shared_paths) == 1:
            msg.setText(f'正在共享: {self.shared_paths[0]}')
        else:
            dir_list = '\n'.join([f'  • {path}' for path in self.shared_paths])
            msg.setText(f'正在共享 {len(self.shared_paths)} 个文件夹:\n{dir_list}')
        
        msg.setInformativeText(f'手机访问地址: http://{ip_address}:{port}\n\n点击"确定"后窗口会最小化到系统托盘。')
        msg.exec_()
        
        # 最小化窗口
        self.showMinimized()
    
    def on_server_error(self, error_message):
        self.status_label.setText(f'服务器启动失败: {error_message}')
        self.share_btn.setEnabled(True)
        QMessageBox.critical(self, '服务器启动失败', error_message)
    
    def closeEvent(self, event):
        """窗口关闭时保存配置"""
        self.save_config()
        super().closeEvent(event)

# ==============================
# 服务器线程类
# ==============================
class ServerThread(QThread):
    server_ready = Signal(str, int)
    server_error = Signal(str)
    
    def __init__(self, shared_paths, port):
        super().__init__()
        self.shared_paths = shared_paths
        self.port = port  # 使用传入的端口
    
    def run(self):
        # 启动后台关机监控线程
        monitor_thread = threading.Thread(target=shutdown_monitor, daemon=True)
        monitor_thread.start()
        
        port = self.port  # 使用实例变量中的端口
        local_ip = get_local_ip()
        
        # 尝试启动服务器
        try:
            server_address = ('', port)
            httpd = ThreadedHTTPServer(server_address, FileShareHandler)
            
            # 设置共享目录
            global shared_dirs
            with shared_dirs_lock:
                shared_dirs.clear()
                shared_dirs.extend(self.shared_paths)
            
            # 发送服务器就绪信号
            self.server_ready.emit(local_ip, port)
            
            # 打印启动信息
            print("=" * 60)
            print("局域网文件共享服务已启动")
            print("=" * 60)
            print(f"共享的文件夹:")
            for i, path in enumerate(self.shared_paths, 1):
                print(f"  {i}. {path}")
            print(f"\n访问地址: http://{local_ip}:{port}")
            print(f"端口: {port}")
            print("=" * 60)
            print("关机控制功能已启用（每5秒扫描一次）")
            print("文本消息功能已启用")
            print("Press Ctrl+C in console to stop.")
            
            httpd.serve_forever()
        except PermissionError:
            error_msg = f"端口 {port} 需要管理员权限"
            print(f"[!] {error_msg}")
            print("    建议改用高位端口如 8000")
            self.server_error.emit(error_msg)
        except OSError as e:
            if e.errno == 10048:
                error_msg = f"端口 {port} 已被占用，请更换端口"
                print(f"[!] {error_msg}")
                self.server_error.emit(error_msg)
            else:
                error_msg = f"启动失败: {e}"
                print(f"[!] {error_msg}")
                self.server_error.emit(error_msg)
        except KeyboardInterrupt:
            print("\n正在关闭服务器...")
        except Exception as e:
            error_msg = f"服务器错误: {e}"
            print(f"[!] {error_msg}")
            self.server_error.emit(error_msg)

# ==============================
# 关机控制逻辑（独立于 HTTP 服务）
# ==============================

def cancel_shutdown():
    """
    取消已计划的关机操作。
    在 Windows 上调用 `shutdown /a`；
    在 Linux/macOS 上无法可靠取消 sleep+poweroff 组合，但会清理提示文件。
    返回是否成功。
    """
    global shutdown_status
    system = sys.platform
    try:
        if system == "win32":
            # Windows: 尝试取消关机
            result = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
            if result.returncode == 0:
                print("Windows 关机已取消。")
            else:
                # 检查是否因为"无进行中关机"而失败（这是正常情况）
                if "There is no shutdown in progress" in result.stderr:
                    print("没有正在进行的关机计划。")
                else:
                    print(f"取消失败: {result.stderr}")
        elif system in ("darwin", "linux", "linux2"):
            # Linux/macos: 无法直接取消后台 sleep + poweroff，但至少告知用户
            print("Linux/macos: 取消关机（依赖文件信号）")
        else:
            print("不支持的操作系统，无法取消关机。")

        # 删除旧版遗留的提示文件（兼容历史版本）
        for f in glob.glob("电脑将于*秒后关机.txt"):
            try:
                os.remove(f)
                print(f"已删除提示文件：{f}")
            except Exception as e:
                print(f"删除提示文件失败 {f}: {e}")

        return True
    except Exception as e:
        print(f"取消关机时出错: {e}")
        return False


def schedule_shutdown(seconds):
    """
    安排系统在指定秒数后关机。
    Windows 使用 `shutdown /s /t N`；
    Linux/macos 仅打印日志（实际关机需配合外部脚本，此处简化处理）。
    返回是否成功触发。
    """
    system = sys.platform
    try:
        if system == "win32":
            result = subprocess.run(["shutdown", "/s", "/t", str(seconds)], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Windows 将在 {seconds} 秒后关机")
                return True
            else:
                print(f"Windows 关机失败: {result.stderr}")
                return False
        elif system in ("darwin", "linux", "linux2"):
            # 实际生产环境可在此处启动后台线程执行 sleep + poweroff
            print(f"Linux/macos: 计划 {seconds} 秒后关机（需权限）")
            return True
        else:
            print("不支持的操作系统")
            return False
    except Exception as e:
        print(f"安排关机失败: {e}")
        return False


def is_positive_integer(s):
    """判断字符串 s 是否为正整数（不含前导零等校验，仅基础检查）"""
    return s.isdigit() and int(s) > 0


def shutdown_monitor():
    """
    后台监控线程：每5秒扫描当前目录下的两个特殊文件：
      - "关机.txt"：内容为秒数，触发关机
      - "取消关机.txt"：触发取消关机
    扫描到后立即处理并删除该文件。
    """
    print("关机监控线程启动...")
    while True:
        try:
            files = os.listdir('.')

            # 检查是否存在"取消关机"指令文件
            if "取消关机.txt" in files:
                print("检测到 取消关机.txt")
                cancel_shutdown()
                try:
                    os.remove("取消关机.txt")
                    print("已删除 取消关机.txt")
                except Exception as e:
                    print(f"删除 取消关机.txt 失败: {e}")

            # 检查是否存在"关机"指令文件
            if "关机.txt" in files:
                try:
                    with open("关机.txt", "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    print(f"读取到关机指令: '{content}'")

                    if is_positive_integer(content):
                        seconds = int(content)
                        print(f"安排 {seconds} 秒后关机...")
                        if schedule_shutdown(seconds):
                            os.remove("关机.txt")
                            print("已删除 关机.txt")
                        else:
                            print("关机安排失败！")
                    else:
                        print("内容不是有效的正整数，忽略。")
                except Exception as e:
                    print(f"处理 关机.txt 出错: {e}")

        except Exception as e:
            print(f"监控线程异常: {e}")

        time.sleep(5)  # 每5秒检查一次


# ==============================
# 多线程 HTTP 服务器
# ==============================

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程处理请求的 HTTP 服务器（每个请求一个线程）"""
    allow_reuse_address = True  # 允许快速重启（避免 TIME_WAIT 状态）


# ==============================
# 自定义请求处理器 - 支持多目录和文本消息
# ==============================

class FileShareHandler(SimpleHTTPRequestHandler):
    """继承自 SimpleHTTPRequestHandler，增强功能，支持多目录共享和文本消息"""

    def translate_path(self, path):
        """
        重写 translate_path 方法以支持多个共享目录。
        根据请求路径决定访问哪个共享目录。
        """
        # 移除查询参数
        path = path.split('?', 1)[0]
        path = path.split('#', 1)[0]
        
        # 标准化路径
        path = urllib.parse.unquote(path, errors='surrogatepass')
        
        # 处理根目录：显示目录选择页面
        if path == '/' or path == '':
            return '/__root__'  # 特殊标记，表示根目录
        
        # 检查是否以 /shareX/ 开头（X 是数字）
        import re
        match = re.match(r'^/share(\d+)/(.*)$', path)
        
        if match:
            share_index = int(match.group(1)) - 1  # 转换为0-based索引
            sub_path = match.group(2)
            
            with shared_dirs_lock:
                if 0 <= share_index < len(shared_dirs):
                    share_dir = shared_dirs[share_index]
                    # 构建完整路径
                    full_path = os.path.join(share_dir, sub_path)
                    
                    # 安全检查：确保路径在共享目录内
                    try:
                        full_path = os.path.abspath(full_path)
                        if full_path.startswith(os.path.abspath(share_dir)):
                            return full_path
                        else:
                            return None  # 路径越界，返回None表示拒绝访问
                    except:
                        return None
        
        # 默认情况：返回None，后续会返回404
        return None

    def log_message(self, format, *args):
        """
        重写日志方法：对 URL 路径进行 URL 解码后再打印，便于阅读中文路径。
        例如将 %E6%96%87%E4%BB%B6.txt 显示为 文件.txt
        """
        decoded_path = urllib.parse.unquote(args[0] if args else self.path)
        super().log_message(format, decoded_path, *args[1:])

    def guess_type(self, path):
        """使用父类的 MIME 类型猜测逻辑"""
        return super().guess_type(path)

    def send_head(self):
        """
        发送 HTTP 响应头。
        如果是特殊根目录，显示目录选择页面；如果是普通目录，返回目录列表；如果是文件，返回文件。
        """
        path = self.translate_path(self.path)
        
        # 处理根目录（显示共享目录列表）
        if path == '/__root__':
            return self.list_shared_dirs()
        
        # 如果路径为None，表示路径越界或无效
        if path is None:
            self.send_error(403, "Access denied")
            return None
        
        # 处理文件或目录
        if os.path.isdir(path):
            # 目录处理：确保以 '/' 结尾，否则重定向
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith('/'):
                self.send_response(301)
                new_parts = (parts[0], parts[1], parts[2] + '/',
                             parts[3], parts[4])
                new_url = urllib.parse.urlunsplit(new_parts)
                self.send_header("Location", new_url)
                self.end_headers()
                return None

            # 尝试查找 index.html/index.htm
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                # 无 index 文件，则列出目录
                return self.list_directory(path)

        # 处理文件请求
        if not os.path.exists(path):
            self.send_error(404, "File not found")
            return None
            
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, "File not found")
            return None

        try:
            fs = os.fstat(f.fileno())  # 获取文件元数据
            if 'Range' in self.headers:
                # 客户端请求分段（如视频拖动），走 Range 处理
                self.range_request(f, fs, ctype)
                return f
            else:
                # 普通完整文件请求
                self.send_response(200)
                self.send_header("Content-type", ctype)
                self.send_header("Content-Length", str(fs[6]))
                self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
                self.end_headers()
                return f
        except:
            f.close()
            raise

    def list_shared_dirs(self):
        """生成共享目录选择页面"""
        with shared_dirs_lock:
            dir_count = len(shared_dirs)
        
        # 构建 HTML 页面
        r = []
        r.append('<!DOCTYPE html>')
        r.append('<html lang="zh-CN">')
        r.append('<head>')
        r.append('<meta charset="utf-8">')
        r.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
        r.append('<title>局域网文件共享 - 选择目录</title>')
        r.append('<style>')
        r.append('''
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                padding: 20px;
                background-color: #f5f5f5;
                margin: 0;
                max-width: 800px;
                margin: 0 auto;
            }
            .header {
                text-align: center;
                margin-bottom: 30px;
            }
            .header h1 {
                color: #333;
                margin-bottom: 10px;
            }
            .dir-list {
                background: white;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .dir-item {
                padding: 20px;
                border-bottom: 1px solid #eee;
                display: flex;
                align-items: center;
                text-decoration: none;
                color: #333;
                transition: background-color 0.2s;
            }
            .dir-item:hover {
                background-color: #f9f9f9;
                text-decoration: none;
            }
            .dir-item:last-child {
                border-bottom: none;
            }
            .folder-icon {
                width: 40px;
                height: 40px;
                background-color: #4CAF50;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 15px;
                flex-shrink: 0;
            }
            .folder-icon::before {
                content: "📁";
                font-size: 20px;
            }
            .dir-info {
                flex-grow: 1;
            }
            .dir-name {
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 5px;
            }
            .dir-path {
                font-size: 14px;
                color: #666;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .arrow {
                color: #999;
                font-size: 18px;
            }
            .text-message-section {
                text-align: center;
                margin: 20px 0;
                padding: 15px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.1);
            }
            .send-text-btn {
                background-color: #FFC107;
                color: black;
                border: none;
                padding: 10px 16px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                min-width: 79px;
            }
            .send-text-btn:hover {
                background-color: #FFA000;
            }
            .shutdown-section {
                text-align: center;
                margin: 20px 0;
                padding: 15px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.1);
            }
            .shutdown-status {
                font-size: 16px;
                color: #d9534f;
                min-height: 24px;
                margin-bottom: 10px;
            }
            .shutdown-btn {
                background-color: #d9534f;
                color: black;
                border: none;
                padding: 10px 16px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                min-width: 79px;
            }
            .cancel-shutdown-btn {
                background-color: #5cb85c;
                color: black;
                border: none;
                padding: 10px 16px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                min-width: 79px;
            }
            .footer {
                text-align: center;
                margin-top: 30px;
                color: #666;
                font-size: 14px;
            }
            .modal {
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0; top: 0;
                width: 100%; height: 100%;
                background-color: rgba(0,0,0,0.5);
            }
            .modal-content {
                background-color: white;
                margin: 10% auto;
                padding: 20px;
                border-radius: 10px;
                width: 90%;
                max-width: 500px;
                box-sizing: border-box;
            }
            .modal textarea {
                width: 100%;
                padding: 10px;
                margin: 10px 0;
                box-sizing: border-box;
                border: 1px solid #ccc;
                border-radius: 6px;
                min-height: 150px;
                font-size: 14px;
                font-family: inherit;
            }
            .modal button {
                padding: 10px 20px;
                font-size: 14px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                margin: 5px;
            }
            .modal .clipboard-btn {
                background-color: #FF9800;
                color: white;
            }
            .modal .cancel-btn {
                background-color: #f44336;
                color: white;
            }
            .modal .confirm-btn {
                background-color: #4CAF50;
                color: white;
            }
            .modal .copy-btn {
                background-color: #2196F3;
                color: white;
            }
            .modal .close-btn {
                background-color: #9E9E9E;
                color: white;
            }
        ''')
        r.append('</style>')
        r.append('</head>')
        r.append('<body>')

        # 文本消息区域
        #r.append('<div class="text-message-section">')
        #r.append('<button class="send-text-btn" onclick="showSendTextModal()">发送文本</button>')
        #r.append('</div>')

        # 关机控制区域
        r.append('<div class="shutdown-section">')
        r.append(f'<div class="shutdown-status" id="shutdownStatus">{shutdown_status}</div>')
        r.append('<button class="shutdown-btn" onclick="showShutdownModal()">关机</button>')
        r.append('<button class="cancel-shutdown-btn" onclick="cancelShutdown()">取消关机</button>')
        r.append('<button class="send-text-btn" onclick="showSendTextModal()">发送文本</button>')
        r.append('</div>')

        r.append('<div class="header">')
        r.append('<h1>局域网文件共享</h1>')
        r.append(f'<p>共 {dir_count} 个共享文件夹，请选择一个访问：</p>')
        r.append('</div>')

        r.append('<div class="dir-list">')
        
        with shared_dirs_lock:
            for i, dir_path in enumerate(shared_dirs, 1):
                dir_name = os.path.basename(dir_path) if os.path.basename(dir_path) else dir_path
                # 显示缩略路径
                display_path = dir_path
                if len(display_path) > 50:
                    display_path = '...' + display_path[-47:]
                
                r.append(f'<a href="/share{i}/" class="dir-item">')
                r.append('<div class="folder-icon"></div>')
                r.append('<div class="dir-info">')
                r.append(f'<div class="dir-name">{dir_name}</div>')
                r.append(f'<div class="dir-path">{display_path}</div>')
                r.append('</div>')
                r.append('<div class="arrow">→</div>')
                r.append('</a>')
        
        r.append('</div>')
        
        r.append('<div class="footer">')
        r.append('<p>将文件拖拽到GUI窗口可添加更多共享文件夹</p>')
        r.append('</div>')

        # 发送文本模态框
        r.append('''
        <div id="sendTextModal" class="modal">
            <div class="modal-content">
                <h3>发送文本到电脑端</h3>
                <textarea id="sendTextArea" placeholder="在这里输入要发送的文本内容..."></textarea>
                <div style="text-align: center;">
                    <button class="clipboard-btn" onclick="pasteFromClipboard()">剪贴板</button>
                    <button class="cancel-btn" onclick="closeModal('sendTextModal')">取消</button>
                    <button class="confirm-btn" onclick="sendText()">确认</button>
                </div>
                <p id="sendTextResult" style="margin-top:10px; text-align:center;"></p>
            </div>
        </div>
        ''')

        # 接收文本模态框
        r.append('''
        <div id="receiveTextModal" class="modal">
            <div class="modal-content">
                <h3 id="receiveTitle">电脑端消息</h3>
                <p id="receiveMessage"></p>
                <textarea id="receiveTextArea" readonly></textarea>
                <div style="text-align: center;">
                    <button class="copy-btn" onclick="copyToClipboard()">复制</button>
                    <button class="close-btn" onclick="closeModal('receiveTextModal')">关闭</button>
                </div>
            </div>
        </div>
        ''')

        # 关机模态框
        r.append('''
        <div id="shutdownModal" class="modal" style="display:none;">
            <div class="modal-content">
                <h3>安排关机</h3>
                <input type="number" id="shutdownSeconds" placeholder="输入秒数（如：100）" min="1" required style="width:100%; padding:10px; margin:8px 0; box-sizing:border-box;">
                <button type="submit" onclick="scheduleShutdown()" style="width:100%; padding:10px; background-color:#007aff; color:white; border:none; border-radius:6px; cursor:pointer;">确认关机</button>
                <button type="button" class="close" onclick="closeModal('shutdownModal')" style="width:100%; padding:10px; margin-top:10px; background-color:#ccc; border:none; border-radius:6px; cursor:pointer;">取消</button>
                <p id="shutdownResult" style="margin-top:10px;"></p>
            </div>
        </div>
        ''')

        # JavaScript
        r.append('''
        <script>
        let currentMessage = null;
        
        function showSendTextModal() {
            document.getElementById('sendTextModal').style.display = 'block';
            document.getElementById('sendTextArea').value = '';
            document.getElementById('sendTextResult').textContent = '';
        }
        
        function pasteFromClipboard() {
            if (navigator.clipboard && navigator.clipboard.readText) {
                navigator.clipboard.readText().then(text => {
                    document.getElementById('sendTextArea').value = text;
                }).catch(err => {
                    alert('无法访问剪贴板: ' + err);
                });
            } else {
                alert('您的浏览器不支持剪贴板API，请手动粘贴');
            }
        }
        
        function sendText() {
            const text = document.getElementById('sendTextArea').value.trim();
            const resultEl = document.getElementById('sendTextResult');
            
            if (!text) {
                resultEl.innerHTML = '<span style="color:red">请输入文本内容！</span>';
                return;
            }
            
            fetch('/api/send_text', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: text})
            })
            .then(res => {
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">文本已发送！</span>';
                    setTimeout(() => {
                        closeModal('sendTextModal');
                    }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                resultEl.innerHTML = '<span style="color:red">发送失败: ' + err.message + '</span>';
            });
        }
        
        function showReceiveTextModal(title, message, text) {
            document.getElementById('receiveTitle').textContent = title;
            document.getElementById('receiveMessage').textContent = message;
            document.getElementById('receiveTextArea').value = text;
            document.getElementById('receiveTextModal').style.display = 'block';
            currentMessage = text;
        }
        
        function copyToClipboard() {
            if (currentMessage) {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(currentMessage).then(() => {
                        alert('文本已复制到剪贴板');
                    }).catch(err => {
                        alert('复制失败: ' + err);
                    });
                } else {
                    // 降级方案
                    const textarea = document.createElement('textarea');
                    textarea.value = currentMessage;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                    alert('文本已复制到剪贴板');
                }
            }
        }
        
        function closeModal(id) {
            document.getElementById(id).style.display = 'none';
            if (id === 'sendTextModal') {
                document.getElementById('sendTextResult').textContent = '';
            }
        }
        
        function showShutdownModal() {
            document.getElementById('shutdownModal').style.display = 'block';
        }
        
        function scheduleShutdown() {
            const seconds = document.getElementById('shutdownSeconds').value.trim();
            const resultEl = document.getElementById('shutdownResult');
            if (!seconds || isNaN(seconds) || parseInt(seconds) <= 0) {
                resultEl.innerHTML = '<span style="color:red">请输入有效的正整数！</span>';
                return;
            }
            fetch('/api/shutdown', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({seconds: parseInt(seconds)})
            })
            .then(res => {
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">关机指令已发送！</span>';
                    setTimeout(() => {
                        closeModal('shutdownModal');
                        updateStatus();
                    }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                resultEl.innerHTML = '<span style="color:red">错误: ' + err.message + '</span>';
            });
        }
        
        function cancelShutdown() {
            if (!confirm('确定要取消电脑端关机吗？')) return;
            fetch('/api/cancel_shutdown', { method: 'POST' })
            .then(res => {
                if (res.ok) {
                    updateStatus();
                } else {
                    alert('取消关机失败，请重试。');
                }
            })
            .catch(err => {
                alert('请求失败: ' + err.message);
            });
        }
        
        function updateStatus() {
            fetch('/api/shutdown_status')
            .then(res => res.json())
            .then(data => {
                document.getElementById('shutdownStatus').textContent = data.status;
            })
            .catch(() => {});
        }
        
        // 检查是否有新消息
        function checkForMessages() {
            fetch('/api/check_message')
            .then(res => {
                if (res.ok) {
                    return res.json();
                }
                return null;
            })
            .then(data => {
                if (data && data.has_message) {
                    const title = "电脑端消息";
                    const message = `电脑端 IP: ${data.sender_ip} 给你发送文本消息：`;
                    showReceiveTextModal(title, message, data.text);
                    
                    // 确认已接收
                    fetch('/api/confirm_message', { method: 'POST' });
                }
            })
            .catch(() => {});
        }
        
        // 初始加载状态
        updateStatus();
        
        // 定期检查消息
        setInterval(checkForMessages, 2000);
        
        // 点击模态框背景关闭
        window.onclick = function(event) {
            if (event.target.classList.contains('modal')) {
                event.target.style.display = 'none';
            }
        }
        </script>
        ''')

        encoded = '\n'.join(r).encode('utf-8', 'surrogateescape')
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        return None

    def range_request(self, f, fs, ctype):
        """
        处理 HTTP Range 请求（用于视频/音频流式播放）。
        返回 206 Partial Content，并设置 Content-Range 头。
        """
        file_size = fs[6]
        range_header = self.headers.get('Range', None)
        if not range_header:
            return

        # 解析 Range: bytes=0-1023 或 bytes=500-
        range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if not range_match:
            self.send_error(416, "Requested Range Not Satisfiable")
            f.close()
            return

        start = int(range_match.group(1))
        end = range_match.group(2)
        end = int(end) if end else file_size - 1

        # 校验范围合法性
        if start >= file_size or end >= file_size or start > end:
            self.send_error(416, "Requested Range Not Satisfiable")
            f.close()
            return

        length = end - start + 1
        f.seek(start)  # 移动文件指针到起始位置

        # 发送 206 响应
        self.send_response(206)
        self.send_header("Content-type", ctype)
        self.send_header("Accept-Ranges", "bytes")  # 告知客户端支持分段
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()

    def copyfile(self, source, outputfile):
        """
        将文件内容复制到输出流。
        区分 Range 请求（调用 copyfile_range）和普通请求（调用父类 copyfile）。
        对普通请求包裹异常处理，防止客户端断开导致 traceback。
        """
        if 'Range' in self.headers:
            range_header = self.headers.get('Range')
            range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if range_match:
                start = int(range_match.group(1))
                end = range_match.group(2)
                end = int(end) if end else os.fstat(source.fileno()).st_size - 1
                length = end - start + 1
                self.copyfile_range(source, outputfile, length)
                return

        # 普通完整文件下载（HTTP 200）
        try:
            super().copyfile(source, outputfile)
        except (ConnectionResetError, BrokenPipeError):
            # 客户端（如手机浏览器）提前关闭连接，属于正常现象，静默忽略
            return
        except OSError as e:
            # 兼容不同系统错误码：Windows 10054, Unix-like 32 (EPIPE)
            if e.errno in (10054, 32):
                return
            else:
                raise  # 其他真实 I/O 错误仍需抛出

    def copyfile_range(self, source, outputfile, length):
        """
        分段复制文件内容（用于 Range 请求）。
        同样捕获客户端断开异常，避免命令行报错。
        """
        bufsize = 64 * 1024  # 64KB 缓冲区
        try:
            while length > 0:
                to_read = min(bufsize, length)
                buf = source.read(to_read)
                if not buf:
                    break
                outputfile.write(buf)
                length -= len(buf)
        except (ConnectionResetError, BrokenPipeError):
            # 客户端提前关闭连接，静默忽略
            return
        except OSError as e:
            if e.errno in (10054, 32):  # 10054: Connection reset by peer; 32: Broken pipe
                return
            else:
                raise  # 非预期错误，继续抛出

    def list_directory(self, path):
        """
        生成目录列表的 HTML 页面。
        包含关机控制、文件操作按钮、文件列表、模态框（Modal）和 JavaScript。
        """
        try:
            names = os.listdir(path)
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None

        # 排序：目录在前，文件在后；同类型按名称升序（忽略大小写）
        names.sort(key=lambda a: (not os.path.isdir(os.path.join(path, a)), a.lower()))
        
        # 获取当前相对路径
        current_url = self.path
        # 使用 urllib.parse.unquote 解码中文路径
        displaypath = urllib.parse.unquote(current_url, errors='surrogatepass')
        
        # 获取共享目录索引和相对路径
        import re
        match = re.match(r'^/share(\d+)/(.*)$', current_url)
        share_index = 1
        if match:
            share_index = match.group(1)
            rel_path = urllib.parse.unquote(match.group(2), errors='surrogatepass')
            if rel_path:
                displaypath = f"share{share_index}/{rel_path}"
            else:
                displaypath = f"share{share_index}/"

        # 构建 HTML 页面 - 保持原有样式不变
        r = []
        r.append('<!DOCTYPE html>')
        r.append('<html lang="zh-CN">')
        r.append('<head>')
        r.append('<meta charset="utf-8">')
        r.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')  # 响应式
        r.append('<title>局域网文件共享</title>')
        r.append('<style>')
        r.append('''
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                padding: 16px;
                background-color: #f5f5f5;
                margin: 0;
            }
            .header {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
                margin-bottom: 20px;
                justify-content: center;
            }
            .header button {
                padding: 10px 16px;
                font-size: 16px;
                border: none;
                border-radius: 6px;
                color: white;
                cursor: pointer;
                min-width: 100px;
            }
            .shutdown-btn {
                background-color: #d9534f; /* 红色 */
                color: black;
                border: none;
                padding: 10px 16px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                min-width: 79px;
            }
            .cancel-shutdown-btn {
                background-color: #5cb85c; /* 绿色 */
                color: black;
                border: none;
                padding: 10px 16px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                min-width: 79px;
            }
            .normal-btn {
                background-color: #007aff;
            }
            .send-text-btn {
                background-color: #FFC107;
                color: black;
                border: none;
                padding: 10px 16px;
                font-size: 16px;
                border-radius: 6px;
                cursor: pointer;
                min-width: 79px;
            }
            .header button:hover {
                opacity: 0.9;
            }
            .shutdown-section {
                text-align: center;
                margin: 15px 0;
                padding: 12px;
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 5px rgba(0,0,0,0.1);
            }
            .shutdown-status {
                font-size: 16px;
                color: #d9534f;
                min-height: 24px;
            }
            .file-list {
                background: white;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .file-list h2 {
                padding: 16px;
                margin: 0;
                border-bottom: 1px solid #eee;
                font-size: 18px;
            }
            .file-list ul {
                list-style: none;
                padding: 0;
                margin: 0;
            }
            .file-list li {
                padding: 12px 16px;
                border-bottom: 1px solid #eee;
            }
            .file-list li:last-child {
                border-bottom: none;
            }
            .file-list a {
                text-decoration: none;
                color: #007aff;
                font-size: 16px;
                display: block;
            }
            .file-list a:hover {
                text-decoration: underline;
            }
            .modal {
                display: none;
                position: fixed;
                z-index: 1000;
                left: 0; top: 0;
                width: 100%; height: 100%;
                background-color: rgba(0,0,0,0.5);
            }
            .modal-content {
                background-color: white;
                margin: 10% auto;
                padding: 20px;
                border-radius: 10px;
                width: 90%;
                max-width: 500px;
                box-sizing: border-box;
            }
            .modal textarea {
                width: 100%;
                padding: 10px;
                margin: 10px 0;
                box-sizing: border-box;
                border: 1px solid #ccc;
                border-radius: 6px;
                min-height: 150px;
                font-size: 14px;
                font-family: inherit;
            }
            .modal button {
                padding: 10px 20px;
                font-size: 14px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                margin: 5px;
            }
            .modal .clipboard-btn {
                background-color: #FF9800;
                color: white;
            }
            .modal .cancel-btn {
                background-color: #f44336;
                color: white;
            }
            .modal .confirm-btn {
                background-color: #4CAF50;
                color: white;
            }
            .modal .copy-btn {
                background-color: #2196F3;
                color: white;
            }
            .modal .close-btn {
                background-color: #9E9E9E;
                color: white;
            }
            @media (max-width: 600px) {
                .header button { font-size: 14px; padding: 8px 12px; }
            }
        ''')
        r.append('</style>')
        r.append('</head>')
        r.append('<body>')

        # 顶部返回按钮 - 保持原有布局
        r.append('<div class="header">')
        r.append(f'<button class="normal-btn" onclick="window.location.href=\'/\'">返回目录列表</button>')
        r.append('</div>')

        # === 关机控制区域（状态标签在上，按钮在下）===
        r.append('<div class="shutdown-section">')
        r.append(f'<div class="shutdown-status" id="shutdownStatus">{shutdown_status}</div>')
        r.append('<button class="shutdown-btn" onclick="showShutdownModal()">关机</button>')
        r.append('<button class="cancel-shutdown-btn" onclick="cancelShutdown()">取消关机</button>')
        r.append('<button class="send-text-btn" onclick="showSendTextModal()">发送文本</button>')
        r.append('</div>')

        # 顶部功能按钮：新建文件、目录、上传
        r.append('<div class="header">')
        r.append('<button class="normal-btn" onclick="showCreateFileModal()">新建文件</button>')
        r.append('<button class="normal-btn" onclick="showCreateDirModal()">新建目录</button>')
        r.append('<button class="normal-btn" onclick="showUploadModal()">上传文件</button>')
        r.append('</div>')

        # 文件列表
        r.append('<div class="file-list">')
        r.append(f'<h2>目录：{displaypath}</h2>')
        r.append('<ul>')

        # 添加返回上级目录链接（如果不是根目录）
        if displaypath != f'share{share_index}/':
            r.append('<li><a href="../">../</a></li>')

        # 遍历当前目录所有文件/目录 - 只修改这里，使用html.escape处理显示名称
        for name in names:
            fullname = os.path.join(path, name)
            display_name = name
            linkname = name
            is_dir = os.path.isdir(fullname)
            if is_dir:
                display_name = name + "/"
                linkname = name + "/"

            quoted_link = urllib.parse.quote(linkname, safe='/')  # URL 编码（保留 /）
            ext = os.path.splitext(name)[1].lower()

            # 使用html.escape确保中文和特殊字符正确显示
            from html import escape
            escaped_display_name = escape(display_name)
            
            if is_dir:
                # 目录：直接链接
                r.append(f'<li><a href="{quoted_link}">{escaped_display_name}</a></li>')
            elif ext in PREVIEW_EXTENSIONS:
                # 支持预览的文件：直接链接（浏览器会尝试打开）
                r.append(f'<li><a href="{quoted_link}">{escaped_display_name}</a></li>')
            else:
                # 其他文件：点击时弹出确认框（避免误点大文件）
                # 注意：JavaScript字符串中的引号需要转义
                js_escaped = escaped_display_name.replace("'", "\\'").replace('"', '\\"')
                r.append(f'<li><a href="{quoted_link}" onclick="return confirmDownload(\'{js_escaped}\')">{escaped_display_name}</a></li>')

        r.append('</ul>')
        r.append('</div>')

        # ========== Modals（模态框）==========
        # 发送文本模态框
        r.append('''
        <div id="sendTextModal" class="modal">
            <div class="modal-content">
                <h3>发送文本到电脑端</h3>
                <textarea id="sendTextArea" placeholder="在这里输入要发送的文本内容..."></textarea>
                <div style="text-align: center;">
                    <button class="clipboard-btn" onclick="pasteFromClipboard()">剪贴板</button>
                    <button class="cancel-btn" onclick="closeModal('sendTextModal')">取消</button>
                    <button class="confirm-btn" onclick="sendText()">确认</button>
                </div>
                <p id="sendTextResult" style="margin-top:10px; text-align:center;"></p>
            </div>
        </div>
        ''')

        # 接收文本模态框
        r.append('''
        <div id="receiveTextModal" class="modal">
            <div class="modal-content">
                <h3 id="receiveTitle">电脑端消息</h3>
                <p id="receiveMessage"></p>
                <textarea id="receiveTextArea" readonly></textarea>
                <div style="text-align: center;">
                    <button class="copy-btn" onclick="copyToClipboard()">复制</button>
                    <button class="close-btn" onclick="closeModal('receiveTextModal')">关闭</button>
                </div>
            </div>
        </div>
        ''')

        # 原有模态框
        r.append('''
        <div id="shutdownModal" class="modal">
            <div class="modal-content">
                <h3>安排关机</h3>
                <input type="number" id="shutdownSeconds" placeholder="输入秒数（如：100）" min="1" required>
                <button type="submit" onclick="scheduleShutdown()">确认关机</button>
                <button type="button" class="close" onclick="closeModal('shutdownModal')">取消</button>
                <p id="shutdownResult" style="margin-top:10px;"></p>
            </div>
        </div>

        <div id="createFileModal" class="modal">
            <div class="modal-content">
                <h3>新建 .txt 文件</h3>
                <input type="text" id="newFileName" placeholder="例如：笔记.txt" required>
                <textarea id="newFileContent" placeholder="文件内容（可选）" rows="5"></textarea>
                <button type="submit" onclick="createFile()">创建</button>
                <button type="button" class="close" onclick="closeModal('createFileModal')">取消</button>
                <p id="createFileResult" style="margin-top:10px;"></p>
            </div>
        </div>

        <div id="createDirModal" class="modal">
            <div class="modal-content">
                <h3>新建目录</h3>
                <input type="text" id="newDirName" placeholder="例如：我的文件夹" required>
                <button type="submit" onclick="createDir()">创建</button>
                <button type="button" class="close" onclick="closeModal('createDirModal')">取消</button>
                <p id="createDirResult" style="margin-top:10px;"></p>
            </div>
        </div>

        <div id="uploadModal" class="modal">
            <div class="modal-content">
                <h3>上传文件</h3>
                <input type="file" id="uploadFileInput" onchange="previewFileName(this)">
                <div id="uploadFileName" style="margin: 8px 0; font-size:14px; color:#666;"></div>
                <button type="submit" onclick="uploadFile()" id="uploadBtn">上传</button>
                <button type="button" class="close" onclick="closeModal('uploadModal')">取消</button>
                <p id="uploadResult" style="margin-top:10px;"></p>
            </div>
        </div>
        ''')

        # ========== JavaScript 逻辑 ==========
        r.append('''
        <script>
        let currentMessage = null;
        
        // 文本消息功能
        function showSendTextModal() {
            document.getElementById('sendTextModal').style.display = 'block';
            document.getElementById('sendTextArea').value = '';
            document.getElementById('sendTextResult').textContent = '';
        }
        
        function pasteFromClipboard() {
            if (navigator.clipboard && navigator.clipboard.readText) {
                navigator.clipboard.readText().then(text => {
                    document.getElementById('sendTextArea').value = text;
                }).catch(err => {
                    alert('无法访问剪贴板: ' + err);
                });
            } else {
                alert('您的浏览器不支持剪贴板API，请手动粘贴');
            }
        }
        
        function sendText() {
            const text = document.getElementById('sendTextArea').value.trim();
            const resultEl = document.getElementById('sendTextResult');
            
            if (!text) {
                resultEl.innerHTML = '<span style="color:red">请输入文本内容！</span>';
                return;
            }
            
            fetch('/api/send_text', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: text})
            })
            .then(res => {
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">文本已发送！</span>';
                    setTimeout(() => {
                        closeModal('sendTextModal');
                    }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                resultEl.innerHTML = '<span style="color:red">发送失败: ' + err.message + '</span>';
            });
        }
        
        function showReceiveTextModal(title, message, text) {
            document.getElementById('receiveTitle').textContent = title;
            document.getElementById('receiveMessage').textContent = message;
            document.getElementById('receiveTextArea').value = text;
            document.getElementById('receiveTextModal').style.display = 'block';
            currentMessage = text;
        }
        
        function copyToClipboard() {
            if (currentMessage) {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(currentMessage).then(() => {
                        alert('文本已复制到剪贴板');
                    }).catch(err => {
                        alert('复制失败: ' + err);
                    });
                } else {
                    // 降级方案
                    const textarea = document.createElement('textarea');
                    textarea.value = currentMessage;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                    alert('文本已复制到剪贴板');
                }
            }
        }
        
        // 检查是否有新消息
        function checkForMessages() {
            fetch('/api/check_message')
            .then(res => {
                if (res.ok) {
                    return res.json();
                }
                return null;
            })
            .then(data => {
                if (data && data.has_message) {
                    const title = "电脑端消息";
                    const message = `电脑端 IP: ${data.sender_ip} 给你发送文本消息：`;
                    showReceiveTextModal(title, message, data.text);
                    
                    // 确认已接收
                    fetch('/api/confirm_message', { method: 'POST' });
                }
            })
            .catch(() => {});
        }
        
        // 定期检查消息
        setInterval(checkForMessages, 2000);
        
        // 原有功能
        function confirmDownload(filename) {
            return confirm('确定要下载 "' + filename + '" 吗？');
        }

        function showModal(id) { document.getElementById(id).style.display = 'block'; }
        function closeModal(id) {
            document.getElementById(id).style.display = 'none';
            const map = {
                'shutdownModal': 'shutdownResult',
                'createFileModal': 'createFileResult',
                'createDirModal': 'createDirResult',
                'uploadModal': 'uploadResult',
                'sendTextModal': 'sendTextResult'
            };
            if (map[id]) document.getElementById(map[id]).textContent = '';
            if (id === 'shutdownModal') document.getElementById('shutdownSeconds').value = '';
            if (id === 'createFileModal') {
                document.getElementById('newFileName').value = '';
                document.getElementById('newFileContent').value = '';
            }
            if (id === 'createDirModal') document.getElementById('newDirName').value = '';
            if (id === 'uploadModal') {
                document.getElementById('uploadFileInput').value = '';
                document.getElementById('uploadFileName').textContent = '';
            }
            if (id === 'sendTextModal') {
                document.getElementById('sendTextArea').value = '';
            }
        }
        function showShutdownModal() { showModal('shutdownModal'); }
        function showCreateFileModal() { showModal('createFileModal'); }
        function showCreateDirModal() { showModal('createDirModal'); }
        function showUploadModal() { showModal('uploadModal'); }

        function scheduleShutdown() {
            const seconds = document.getElementById('shutdownSeconds').value.trim();
            const resultEl = document.getElementById('shutdownResult');
            if (!seconds || isNaN(seconds) || parseInt(seconds) <= 0) {
                resultEl.innerHTML = '<span style="color:red">请输入有效的正整数！</span>';
                return;
            }
            fetch('/api/shutdown', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({seconds: parseInt(seconds)})
            })
            .then(res => {
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">关机指令已发送！</span>';
                    setTimeout(() => {
                        closeModal('shutdownModal');
                        updateStatus(); // 刷新状态
                    }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                resultEl.innerHTML = '<span style="color:red">错误: ' + err.message + '</span>';
            });
        }

        function cancelShutdown() {
            if (!confirm('确定要取消电脑端关机吗？')) return;
            fetch('/api/cancel_shutdown', { method: 'POST' })
            .then(res => {
                if (res.ok) {
                    updateStatus();
                } else {
                    alert('取消关机失败，请重试。');
                }
            })
            .catch(err => {
                alert('请求失败: ' + err.message);
            });
        }

        function createFile() {
            const name = document.getElementById('newFileName').value.trim();
            const content = document.getElementById('newFileContent').value;
            const resultEl = document.getElementById('createFileResult');
            if (!name || !name.endsWith('.txt')) {
                resultEl.innerHTML = '<span style="color:red">文件名必须以 .txt 结尾！</span>';
                return;
            }
            fetch('/api/create_file', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({filename: name, content: content})
            })
            .then(res => {
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">文件创建成功！</span>';
                    setTimeout(() => { closeModal('createFileModal'); window.location.reload(); }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                resultEl.innerHTML = '<span style="color:red">错误: ' + err.message + '</span>';
            });
        }

        function createDir() {
            const name = document.getElementById('newDirName').value.trim();
            const resultEl = document.getElementById('createDirResult');
            if (!name) {
                resultEl.innerHTML = '<span style="color:red">目录名不能为空！</span>';
                return;
            }
            fetch('/api/create_dir', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({dirname: name})
            })
            .then(res => {
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">目录创建成功！</span>';
                    setTimeout(() => { closeModal('createDirModal'); window.location.reload(); }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                resultEl.innerHTML = '<span style="color:red">错误: ' + err.message + '</span>';
            });
        }

        function previewFileName(input) {
            const nameEl = document.getElementById('uploadFileName');
            if (input.files.length > 0) {
                nameEl.textContent = '选择文件: ' + input.files[0].name;
            } else {
                nameEl.textContent = '';
            }
        }

        function uploadFile() {
            const fileInput = document.getElementById('uploadFileInput');
            const resultEl = document.getElementById('uploadResult');
            const btn = document.getElementById('uploadBtn');
            if (!fileInput.files.length) {
                resultEl.innerHTML = '<span style="color:red">请选择一个文件！</span>';
                return;
            }

            const file = fileInput.files[0];
            const formData = new FormData();
            formData.append('file', file);
            formData.append('filename', file.name);

            btn.disabled = true;
            btn.textContent = '上传中...';

            fetch('/api/upload', {
                method: 'POST',
                body: formData
            })
            .then(res => {
                btn.disabled = false;
                btn.textContent = '上传';
                if (res.ok) {
                    resultEl.innerHTML = '<span style="color:green">上传成功！</span>';
                    setTimeout(() => { closeModal('uploadModal'); window.location.reload(); }, 1000);
                } else {
                    return res.text().then(t => { throw new Error(t); });
                }
            })
            .catch(err => {
                btn.disabled = false;
                btn.textContent = '上传';
                resultEl.innerHTML = '<span style="color:red">错误: ' + err.message + '</span>';
            });
        }

        function updateStatus() {
            fetch('/api/shutdown_status')
            .then(res => res.json())
            .then(data => {
                document.getElementById('shutdownStatus').textContent = data.status;
            })
            .catch(() => {});
        }

        updateStatus();

        window.onclick = function(event) {
            if (event.target.classList.contains('modal')) {
                event.target.style.display = 'none';
            }
        }
        </script>
        ''')

        # 发送完整 HTML 响应
        encoded = '\n'.join(r).encode('utf-8', 'surrogateescape')
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        return None

    def do_POST(self):
        """
        处理所有 POST 请求（API 接口）。
        包括：关机、取消关机、新建文件、新建目录、上传文件、文本消息。
        """
        global shutdown_status
        
        # 处理文本消息相关API
        if self.path == '/api/send_text':
            # 手机端发送文本到电脑端
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                text = data.get('text', '').strip()
                
                if not text:
                    self.send_error(400, "文本内容不能为空")
                    return
                
                # 获取客户端IP
                client_ip = self.client_address[0]
                
                # 保存消息到文件
                message_data = {
                    "text": text,
                    "sender_ip": client_ip,
                    "timestamp": time.time(),
                    "sender_type": "mobile"
                }
                
                with open("mobile_text_message.json", "w", encoding="utf-8") as f:
                    json.dump(message_data, f, ensure_ascii=False, indent=2)
                
                print(f"收到来自 {client_ip} 的文本消息: {text[:50]}...")
                
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_error(500, str(e))
            return
        
        elif self.path == '/api/check_message':
            # 检查是否有电脑端发送的消息
            try:
                if os.path.exists("text_message.json"):
                    with open("text_message.json", "r", encoding="utf-8") as f:
                        message_data = json.load(f)
                    
                    response = {
                        "has_message": True,
                        "text": message_data.get("text", ""),
                        "sender_ip": message_data.get("sender_ip", "未知IP")
                    }
                else:
                    response = {"has_message": False}
                
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_error(500, str(e))
            return
        
        elif self.path == '/api/confirm_message':
            # 确认消息已接收，删除消息文件
            try:
                if os.path.exists("text_message.json"):
                    os.remove("text_message.json")
                    print("文本消息已确认接收")
                
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_error(500, str(e))
            return
        
        # 原有API处理
        if self.path in ['/api/shutdown', '/api/cancel_shutdown', '/api/create_file', 
                        '/api/create_dir', '/api/upload', '/api/shutdown_status']:
            pass
        else:
            path = self.translate_path(self.path)
            if path == '/__root__' or path is None:
                self.send_error(403, "Cannot perform this operation at root level")
                return
        
        if self.path == '/api/shutdown':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                seconds = data.get('seconds')
                if not isinstance(seconds, int) or seconds <= 0:
                    self.send_error(400, "秒数必须是正整数")
                    return

                with open("关机.txt", "w", encoding="utf-8") as f:
                    f.write(str(seconds))

                with shutdown_lock:
                    shutdown_status = f"电脑端将于{seconds}秒后关机"

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_error(500, str(e))

        elif self.path == '/api/cancel_shutdown':
            try:
                with open("取消关机.txt", "w", encoding="utf-8") as f:
                    f.write("")

                with shutdown_lock:
                    shutdown_status = "电脑端已取消关机"

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_error(500, str(e))

        elif self.path == '/api/create_file':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                filename = data.get('filename', '').strip()
                content = data.get('content', '')

                if not filename.endswith('.txt'):
                    self.send_error(400, "Only .txt files are allowed.")
                    return
                if '..' in filename or '/' in filename or '\\' in filename:
                    self.send_error(400, "Invalid filename.")
                    return

                referer = self.headers.get('Referer', '')
                import re
                match = re.match(r'.*(/share\d+/.*)$', referer)
                
                if match:
                    current_path = match.group(1)
                    path = self.translate_path(current_path)
                    if path and os.path.isdir(path):
                        filepath = os.path.join(path, filename)
                    else:
                        self.send_error(400, "Invalid current directory")
                        return
                else:
                    with shared_dirs_lock:
                        if shared_dirs:
                            filepath = os.path.join(shared_dirs[0], filename)
                        else:
                            self.send_error(400, "No shared directories available")
                            return

                if os.path.exists(filepath):
                    self.send_error(409, "File already exists.")
                    return

                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)

                self.send_response(201)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_error(500, str(e))

        elif self.path == '/api/create_dir':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
                dirname = data.get('dirname', '').strip()

                if not dirname:
                    self.send_error(400, "Directory name cannot be empty.")
                    return
                if '..' in dirname or '/' in dirname or '\\' in dirname:
                    self.send_error(400, "Invalid directory name.")
                    return

                referer = self.headers.get('Referer', '')
                import re
                match = re.match(r'.*(/share\d+/.*)$', referer)
                
                if match:
                    current_path = match.group(1)
                    path = self.translate_path(current_path)
                    if path and os.path.isdir(path):
                        dirpath = os.path.join(path, dirname)
                    else:
                        self.send_error(400, "Invalid current directory")
                        return
                else:
                    with shared_dirs_lock:
                        if shared_dirs:
                            dirpath = os.path.join(shared_dirs[0], dirname)
                        else:
                            self.send_error(400, "No shared directories available")
                            return

                if os.path.exists(dirpath):
                    self.send_error(409, "Directory already exists.")
                    return

                os.makedirs(dirpath)
                self.send_response(201)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())
            except Exception as e:
                self.send_error(500, str(e))

        elif self.path == '/api/upload':
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self.send_error(400, "Invalid content type")
                return

            try:
                from cgi import parse_header, parse_multipart

                _, pdict = parse_header(content_type)
                pdict['boundary'] = pdict['boundary'].encode()
                pdict['CONTENT-LENGTH'] = self.headers['Content-Length']

                form_data = parse_multipart(self.rfile, pdict)
                file_items = form_data.get('file')
                filenames = form_data.get('filename')

                if not file_items or not filenames:
                    self.send_error(400, "No file uploaded")
                    return

                file_content = file_items[0]
                filename = filenames[0].strip()

                if not filename:
                    self.send_error(400, "Empty filename")
                    return
                if '..' in filename or '/' in filename or '\\' in filename:
                    self.send_error(400, "Invalid filename")
                    return

                referer = self.headers.get('Referer', '')
                import re
                match = re.match(r'.*(/share\d+/.*)$', referer)
                
                if match:
                    current_path = match.group(1)
                    path = self.translate_path(current_path)
                    if path and os.path.isdir(path):
                        filepath = os.path.join(path, filename)
                    else:
                        self.send_error(400, "Invalid current directory")
                        return
                else:
                    with shared_dirs_lock:
                        if shared_dirs:
                            filepath = os.path.join(shared_dirs[0], filename)
                        else:
                            self.send_error(400, "No shared directories available")
                            return

                if os.path.exists(filepath):
                    self.send_error(409, "File already exists")
                    return

                with open(filepath, 'wb') as f:
                    f.write(file_content)

                self.send_response(201)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode())

            except Exception as e:
                self.send_error(500, str(e))

        elif self.path == '/api/shutdown_status':
            with shutdown_lock:
                status = shutdown_status
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": status}).encode())
        else:
            self.send_error(404)

    def do_GET(self):
        """
        处理 GET 请求。
        特殊路径 /api/shutdown_status 返回当前关机状态；
        其他路径交由自定义逻辑处理。
        """
        if self.path.startswith('/api/'):
            self.do_POST()  # API请求统一由do_POST处理
        else:
            super().do_GET()


# ==============================
# 工具函数
# ==============================

def get_local_ip():
    """
    获取本机在局域网中的 IPv4 地址。
    通过连接一个不存在的公网地址（不发送数据）来获取出口 IP。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


# ==============================
# 主程序入口
# ==============================

def main():
    # 创建空的 favicon.ico 文件（避免浏览器反复请求 404）
    favicon_path = os.path.join(os.path.dirname(__file__), 'favicon.ico')
    if not os.path.exists(favicon_path):
        with open(favicon_path, 'wb') as f:
            pass  # 创建空文件
    
    # 启动GUI应用程序
    app = QApplication(sys.argv)
    window = FolderShareWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()