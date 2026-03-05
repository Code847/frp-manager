// FRP Manager Web UI JavaScript

class FRPManagerUI {
    constructor() {
        this.initElements();
        this.initEventListeners();
        this.pollStatus();
        this.loadConfig('client');
    }
    
    initElements() {
        // 配置编辑器元素
        this.configType = document.getElementById('configType');
        this.configEditor = document.getElementById('configEditor');
        this.loadBtn = document.getElementById('loadBtn');
        this.saveBtn = document.getElementById('saveBtn');
        
        // 控制中心元素
        this.startBtn = document.getElementById('startBtn');
        this.stopBtn = document.getElementById('stopBtn');
        
        // 日志元素
        this.logContent = document.getElementById('logContent');
        this.clearLogBtn = document.getElementById('clearLogBtn');
        this.logLines = document.getElementById('logLines');
        
        // 状态元素
        this.frpStatusText = document.getElementById('frpStatusText');
    }
    
    initEventListeners() {
        // 配置编辑器事件
        this.loadBtn.addEventListener('click', () => this.loadConfig(this.configType.value));
        this.saveBtn.addEventListener('click', () => this.saveConfig(this.configType.value));
        this.configType.addEventListener('change', () => this.loadConfig(this.configType.value));
        
        // 控制中心事件
        this.startBtn.addEventListener('click', () => this.startFRP());
        this.stopBtn.addEventListener('click', () => this.stopFRP());
        
        // 日志事件
        this.clearLogBtn.addEventListener('click', () => this.clearLog());
        this.logLines.addEventListener('change', () => this.loadLog());
        
        // 定期刷新日志
        setInterval(() => this.loadLog(), 5000);
    }
    
    async pollStatus() {
        try {
            const response = await fetch('/api/status');
            const status = await response.json();
            
            // 获取状态文本元素
            const statusElement = document.getElementById('frpStatusText');
            if (!statusElement) {
                console.error('找不到状态元素 frpStatusText');
                return;
            }
            
            if (status.running) {
                statusElement.innerHTML = `运行中 (PID: ${status.pid})`;
                statusElement.style.color = '#11998e';
            } else {
                statusElement.innerHTML = '未运行';
                statusElement.style.color = '#ee5a24';
            }
        } catch (error) {
            console.error('获取状态错误:', error);
            const statusElement = document.getElementById('frpStatusText');
            if (statusElement) {
                statusElement.innerHTML = '无法获取状态';
                statusElement.style.color = '#ee5a24';
            }
        }
        
        // 定期轮询状态
        setTimeout(() => this.pollStatus(), 3000);
    }
    
    async loadConfig(configType) {
        try {
            const response = await fetch(`/api/config/${configType}`);
            const data = await response.json();
            this.configEditor.value = data.content;
            this.showMessage('配置加载成功', 'success');
        } catch (error) {
            this.showMessage('加载配置失败', 'error');
        }
    }
    
    async saveConfig(configType) {
        const content = this.configEditor.value;
        if (!content.trim()) {
            this.showMessage('配置内容不能为空', 'warning');
            return;
        }
        
        try {
            const formData = new FormData();
            formData.append('content', content);
            
            const response = await fetch(`/api/config/${configType}`, {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            if (data.success) {
                this.showMessage('配置保存成功', 'success');
            } else {
                this.showMessage('配置保存失败', 'error');
            }
        } catch (error) {
            this.showMessage('保存配置失败', 'error');
        }
    }
    
    async startFRP() {
        try {
            // 启动FRP
            const startResponse = await fetch('/api/start', {
                method: 'POST'
            });
            
            const startData = await startResponse.json();
            if (startData.success) {
                this.showMessage(startData.message, 'success');
                // 刷新日志
                setTimeout(() => this.loadLog(), 1000);
            } else {
                this.showMessage(startData.message, 'error');
            }
        } catch (error) {
            console.error('启动错误:', error);
            this.showMessage('启动FRP失败，请检查配置', 'error');
        }
    }
    
    async stopFRP() {
        try {
            const response = await fetch('/api/stop', {
                method: 'POST'
            });
            
            const data = await response.json();
            if (data.success) {
                this.showMessage('FRP停止成功', 'success');
            } else {
                this.showMessage('FRP停止失败', 'error');
            }
        } catch (error) {
            this.showMessage('停止FRP失败', 'error');
        }
    }
    
    async loadLog() {
        try {
            const lines = this.logLines.value;
            const response = await fetch(`/api/log?lines=${lines}`);
            const data = await response.json();
            this.logContent.textContent = data.content;
            // 滚动到底部
            this.logContent.scrollTop = this.logContent.scrollHeight;
        } catch (error) {
            this.logContent.textContent = '无法加载日志';
        }
    }
    
    async clearLog() {
        // 清空显示的日志
        this.logContent.textContent = '';
        this.showMessage('日志已清空', 'info');
    }
    
    showMessage(message, type = 'info') {
        // 创建消息提示
        const msgDiv = document.createElement('div');
        msgDiv.className = `message message-${type}`;
        msgDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 5px;
            color: white;
            font-weight: 600;
            z-index: 9999;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            max-width: 300px;
            animation: slideIn 0.3s ease;
        `;
        
        // 设置背景色
        switch (type) {
            case 'success':
                msgDiv.style.background = 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)';
                break;
            case 'error':
                msgDiv.style.background = 'linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%)';
                break;
            case 'warning':
                msgDiv.style.background = 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)';
                break;
            default:
                msgDiv.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
        }
        
        msgDiv.textContent = message;
        document.body.appendChild(msgDiv);
        
        // 3秒后自动移除
        setTimeout(() => {
            msgDiv.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (msgDiv.parentNode) {
                    msgDiv.parentNode.removeChild(msgDiv);
                }
            }, 300);
        }, 3000);
    }
}

// 添加动画样式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 初始化UI
document.addEventListener('DOMContentLoaded', () => {
    console.log('FRP Manager UI 初始化中...');
    const ui = new FRPManagerUI();
    console.log('UI已初始化');
    // 立即刷新一次状态
    ui.pollStatus();
});

// 键盘快捷键
document.addEventListener('keydown', (e) => {
    // Ctrl+S 保存配置
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        const saveBtn = document.getElementById('saveBtn');
        saveBtn.click();
    }
    
    // Ctrl+R 刷新日志
    if (e.ctrlKey && e.key === 'r') {
        e.preventDefault();
        const logContent = document.getElementById('logContent');
        if (logContent === document.activeElement) {
            // 如果焦点在日志框，不要刷新
            return;
        }
        // 这里可以添加刷新日志的逻辑
        const frpUI = window.frpUI;
        if (frpUI) {
            frpUI.loadLog();
        }
    }
    
    // Ctrl+Enter 启动服务
    if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        const startBtn = document.getElementById('startBtn');
        startBtn.click();
    }
});