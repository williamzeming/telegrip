// Global state
// 全局状态
let isKeyboardEnabled = false;
let isRobotEngaged = false;
let currentConfig = {};
let warningTimeout = null;
let prefersVrView = false;

// Settings modal functions
// 设置弹窗相关函数
function openSettings() {
  const modal = document.getElementById('settingsModal');
  modal.classList.add('show');
  loadConfiguration();
}

function closeSettings() {
  const modal = document.getElementById('settingsModal');
  modal.classList.remove('show');
}

function loadConfiguration() {
  fetch('/api/config')
    .then(response => response.json())
    .then(config => {
      currentConfig = config;
      populateSettingsForm(config);
    })
    .catch(error => {
      console.error('Error loading configuration:', error);
      alert('Error loading configuration');
    });
}

function populateSettingsForm(config) {
  // Robot arms
  // 机器人机械臂
  document.getElementById('leftArmName').value = config.robot?.left_arm?.name || '';
  document.getElementById('leftArmPort').value = config.robot?.left_arm?.port || '';
  document.getElementById('rightArmName').value = config.robot?.right_arm?.name || '';
  document.getElementById('rightArmPort').value = config.robot?.right_arm?.port || '';
  
  // Network settings
  // 网络设置
  document.getElementById('httpsPort').value = config.network?.https_port || '';
  document.getElementById('websocketPort').value = config.network?.websocket_port || '';
  document.getElementById('hostIp').value = config.network?.host_ip || '';
  
  // Control parameters
  // 控制参数
  document.getElementById('vrScale').value = config.robot?.vr_to_robot_scale || '';
  // 转换为毫秒（ms）
  document.getElementById('sendInterval').value = (config.robot?.send_interval * 1000) || ''; // Convert to ms
  document.getElementById('posStep').value = config.control?.keyboard?.pos_step || '';
  document.getElementById('angleStep').value = config.control?.keyboard?.angle_step || '';
}

function restartSystem() {
  if (!confirm('Are you sure you want to restart the system? This will temporarily disconnect all devices.')) {
    return;
  }

  const restartButton = document.getElementById('restartButton');
  restartButton.disabled = true;
  restartButton.textContent = 'Restarting...';

  fetch('/api/restart', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    }
  })
  .then(response => {
    if (response.ok) {
      // Show restart message and close modal
      // 显示重启提示并关闭弹窗
      alert('System is restarting... The page will reload automatically in a few seconds.');
      closeSettings();
      
      // Try to reconnect after a delay
      // 延迟一段时间后尝试重新连接（刷新页面）
      setTimeout(() => {
        window.location.reload();
      }, 5000);
    } else {
      alert('Failed to restart system. Please restart manually.');
    }
  })
  .catch(error => {
    console.error('Error restarting system:', error);
    alert('Error communicating with server. Please restart manually.');
  })
  .finally(() => {
    restartButton.disabled = false;
    restartButton.textContent = '🔄 Restart System';
  });
}

function saveConfiguration() {
  const form = document.getElementById('settingsForm');
  const formData = new FormData(form);
  
  // Build config object
  // 构建配置对象
  const updatedConfig = {
    robot: {
      left_arm: {
        name: formData.get('leftArmName'),
        port: formData.get('leftArmPort'),
        enabled: true
      },
      right_arm: {
        name: formData.get('rightArmName'),
        port: formData.get('rightArmPort'),
        enabled: true
      },
      vr_to_robot_scale: parseFloat(formData.get('vrScale')),
      // 从毫秒转换为秒
      send_interval: parseFloat(formData.get('sendInterval')) / 1000 // Convert from ms
    },
    network: {
      https_port: parseInt(formData.get('httpsPort')),
      websocket_port: parseInt(formData.get('websocketPort')),
      host_ip: formData.get('hostIp')
    },
    control: {
      keyboard: {
        pos_step: parseFloat(formData.get('posStep')),
        angle_step: parseFloat(formData.get('angleStep'))
      }
    }
  };

  const saveButton = document.getElementById('saveButton');
  saveButton.disabled = true;
  saveButton.textContent = 'Saving...';

  fetch('/api/config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(updatedConfig)
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      alert('Configuration saved successfully! Use the restart button to apply changes.');
    } else {
      alert('Failed to save configuration: ' + (data.error || 'Unknown error'));
    }
  })
  .catch(error => {
    console.error('Error saving configuration:', error);
    alert('Error saving configuration');
  })
  .finally(() => {
    saveButton.disabled = false;
    saveButton.textContent = '💾 Save Configuration';
  });
}

// Update status indicators
// 更新状态指示器
function updateStatus() {
  fetch('/api/status')
    .then(response => response.json())
    .then(data => {
      // Update arm connection indicators (based on device files)
      // 更新机械臂连接指示灯（基于设备文件状态）
      const leftIndicator = document.getElementById('leftArmStatus');
      const rightIndicator = document.getElementById('rightArmStatus');
      const vrIndicator = document.getElementById('vrStatus');
      
      leftIndicator.className = 'status-indicator' + (data.left_arm_connected ? ' connected' : '');
      rightIndicator.className = 'status-indicator' + (data.right_arm_connected ? ' connected' : '');
      vrIndicator.className = 'status-indicator' + (data.vrConnected ? ' connected' : '');
      
      // Update keyboard control status
      // 更新键盘控制开关状态
      isKeyboardEnabled = data.keyboardEnabled;
      const keyboardHelp = document.querySelector('.keyboard-help');
      
      if (isKeyboardEnabled) {
        if (keyboardHelp) keyboardHelp.classList.add('active');
      } else {
        if (keyboardHelp) keyboardHelp.classList.remove('active');
      }
      
      // Update robot engagement status
      // 更新机器人使能（电机上电/下电）状态
      if (data.robotEngaged !== undefined) {
        isRobotEngaged = data.robotEngaged;
        updateEngagementUI();
      }
    })
    .catch(error => {
      console.error('Error fetching status:', error);
    });
}

function updateEngagementUI() {
  const engageBtn = document.getElementById('robotEngageBtn');
  const engageBtnText = document.getElementById('engageBtnText');
  const engagementStatusText = document.getElementById('engagementStatusText');
  const connectionHint = document.getElementById('connectionHint');
  const connectionWarning = document.getElementById('connectionWarning');

  if (isRobotEngaged) {
    engageBtn.classList.add('disconnect');
    engageBtn.classList.remove('needs-attention');
    engageBtnText.textContent = '🔌 Disconnect Robot';
    engagementStatusText.textContent = 'Motors Engaged';
    engagementStatusText.style.color = '#FFFFFF';
    if (connectionHint) connectionHint.style.display = 'none';
    if (connectionWarning) connectionWarning.classList.remove('show');
  } else {
    engageBtn.classList.remove('disconnect');
    engageBtnText.textContent = '🔌 Connect Robot';
    engagementStatusText.textContent = 'Motors Disengaged';
    engagementStatusText.style.color = '#FFFFFF';
    if (connectionHint) connectionHint.style.display = 'block';
  }
}

function showConnectionWarning() {
  const engageBtn = document.getElementById('robotEngageBtn');
  const connectionWarning = document.getElementById('connectionWarning');

  if (!isRobotEngaged) {
    // Add pulsing animation to the connect button
    // 给“连接”按钮加闪烁提示动画
    engageBtn.classList.add('needs-attention');

    // Show the warning message
    // 显示警告信息
    if (connectionWarning) {
      connectionWarning.classList.add('show');
    }

    // Clear any existing timeout
    // 清除已有的定时器
    if (warningTimeout) {
      clearTimeout(warningTimeout);
    }

    // Hide warning and stop pulsing after 5 seconds
    // 5 秒后隐藏警告并停止闪烁
    warningTimeout = setTimeout(() => {
      engageBtn.classList.remove('needs-attention');
      if (connectionWarning) {
        connectionWarning.classList.remove('show');
      }
    }, 5000);
  }
}

function toggleRobotEngagement() {
  const action = isRobotEngaged ? 'disconnect' : 'connect';
  
  fetch('/api/robot', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ action: action })
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      isRobotEngaged = !isRobotEngaged;
      updateEngagementUI();
    } else {
      alert('Failed to ' + action + ' robot: ' + (data.error || 'Unknown error'));
    }
  })
  .catch(error => {
    console.error('Error toggling robot engagement:', error);
    alert('Error communicating with server');
  });
}

// Toggle keyboard control
// 切换键盘控制
function toggleKeyboardControl() {
  const action = isKeyboardEnabled ? 'disable' : 'enable';
  
  fetch('/api/keyboard', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ action: action })
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      isKeyboardEnabled = !isKeyboardEnabled;
      const keyboardHelp = document.querySelector('.keyboard-help');
      
      if (isKeyboardEnabled) {
        if (keyboardHelp) keyboardHelp.classList.add('active');
      } else {
        if (keyboardHelp) keyboardHelp.classList.remove('active');
      }
    } else {
      alert('Failed to toggle keyboard control: ' + (data.error || 'Unknown error'));
    }
  })
  .catch(error => {
    console.error('Error toggling keyboard control:', error);
    alert('Error communicating with server');
  });
}

// Check if running in VR/AR mode
// 判断是否处于 VR/AR 模式
function isVRMode() {
  return window.navigator.xr && document.fullscreenElement;
}

// Update UI based on device
// 根据设备能力/模式更新界面
function updateUIForDevice() {
  const desktopInterface = document.getElementById('desktopInterface');
  if (!desktopInterface) return;

  // Keep the desktop interface visible by default, even on XR-capable
  // browsers. Only hide it after the user explicitly switches to the
  // VR view or once the browser has actually entered VR/fullscreen mode.
  if (isVRMode() || prefersVrView) {
    desktopInterface.style.display = 'none';
  } else {
    desktopInterface.style.display = 'block';
  }
}

// Web-based keyboard control
// 网页端键盘控制
let pressedKeys = new Set();

// Add keyboard event listeners for web-based control
// 为网页端控制添加键盘事件监听
// Use capture phase to intercept keys before browser handles them (e.g., F for fullscreen)
// 使用捕获阶段，在浏览器处理按键前拦截（例如 F 可能触发全屏）
document.addEventListener('keydown', handleKeyDown, { capture: true });
document.addEventListener('keyup', handleKeyUp, { capture: true });

function handleKeyDown(event) {
  // Prevent default browser behavior for our control keys regardless of keyboard state
  // 无论键盘控制是否开启，都阻止这些控制键触发浏览器默认行为
  if (isControlKey(event.code)) {
    event.preventDefault();
  }

  // Show warning if robot is not connected and user presses control keys
  // 如果机器人未连接但用户按了控制键，则显示提示
  if (isControlKey(event.code) && !isRobotEngaged) {
    showConnectionWarning();
    return;
  }

  // Only handle keys if keyboard control is enabled and we're focused on the page
  // 仅在键盘控制启用且未重复按压时处理按键
  if (!isKeyboardEnabled || pressedKeys.has(event.code)) return;

  if (isControlKey(event.code)) {
    pressedKeys.add(event.code);
    sendKeyCommand(event.code, 'press');
  }
}

function handleKeyUp(event) {
  // Prevent default browser behavior for our control keys regardless of keyboard state
  // 无论键盘控制是否开启，都阻止这些控制键触发浏览器默认行为
  if (isControlKey(event.code)) {
    event.preventDefault();
  }
  
  // Only handle keys if keyboard control is enabled
  // 仅在键盘控制启用时处理按键松开
  if (!isKeyboardEnabled || !pressedKeys.has(event.code)) return;
  
  if (isControlKey(event.code)) {
    pressedKeys.delete(event.code);
    sendKeyCommand(event.code, 'release');
  }
}

function isControlKey(code) {
  // Check if this is one of our robot control keys
  // 判断是否为机器人控制按键
  const controlKeys = [
    // Left arm movement
    // 左臂移动
    'KeyW', 'KeyS', 'KeyA', 'KeyD', 'KeyQ', 'KeyE',
    // Left arm wrist
    // 左臂腕部
    'KeyZ', 'KeyX',  // wrist roll
    'KeyR', 'KeyT',  // wrist flex
    'KeyF',          // gripper
    'Tab',           // toggle position control
    // Right arm movement
    // 右臂移动
    'KeyI', 'KeyK', 'KeyJ', 'KeyL', 'KeyU', 'KeyO',
    // Right arm wrist
    // 右臂腕部
    'KeyN', 'KeyM',  // wrist roll
    'KeyH', 'KeyY',  // wrist flex
    'Semicolon',     // gripper
    'Enter',         // toggle position control
    // Global
    // 全局
    'Escape'
  ];
  return controlKeys.includes(code);
}

function sendKeyCommand(keyCode, action) {
  // Convert browser keyCode to our key mapping
  // 将浏览器的 keyCode 映射到后端使用的按键标识
  const keyMap = {
    // Left arm movement
    // 左臂移动
    'KeyW': 'w', 'KeyS': 's', 'KeyA': 'a', 'KeyD': 'd',
    'KeyQ': 'q', 'KeyE': 'e',
    // Left arm wrist
    // 左臂腕部
    'KeyZ': 'z', 'KeyX': 'x',  // wrist roll
    'KeyR': 'r', 'KeyT': 't',  // wrist flex
    'KeyF': 'f',               // gripper
    'Tab': 'tab',              // toggle position control
    // Right arm movement
    // 右臂移动
    'KeyI': 'i', 'KeyK': 'k', 'KeyJ': 'j', 'KeyL': 'l',
    'KeyU': 'u', 'KeyO': 'o',
    // Right arm wrist
    // 右臂腕部
    'KeyN': 'n', 'KeyM': 'm',  // wrist roll
    'KeyH': 'h', 'KeyY': 'y',  // wrist flex
    'Semicolon': ';',          // gripper
    'Enter': 'enter',          // toggle position control
    // Global
    // 全局
    'Escape': 'esc'
  };

  const key = keyMap[keyCode];
  if (!key) return;

  fetch('/api/keypress', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ 
      key: key, 
      action: action 
    })
  })
  .catch(error => {
    console.error('Error sending key command:', error);
  });
}

// Initialize
// 初始化
document.addEventListener('DOMContentLoaded', () => {
  updateUIForDevice();
  
  // Start status monitoring
  // 启动状态轮询
  updateStatus();
  // 每 2 秒更新一次
  setInterval(updateStatus, 2000); // Update every 2 seconds
  
  // Handle VR mode changes
  // 处理 VR 模式变化（全屏变化）
  document.addEventListener('fullscreenchange', updateUIForDevice);

  // Settings form handler
  // 设置表单提交处理
  document.getElementById('settingsForm').addEventListener('submit', (e) => {
    e.preventDefault();
    saveConfiguration();
  });

  // Close modal when clicking outside
  // 点击弹窗外区域时关闭弹窗
  document.getElementById('settingsModal').addEventListener('click', (e) => {
    if (e.target.id === 'settingsModal') {
      closeSettings();
    }
  });
  
  // VR session detection
  // VR 会话检测
  if (navigator.xr && typeof navigator.xr.addEventListener === 'function') {
    navigator.xr.addEventListener('sessionstart', () => {
      updateStatus();
      updateUIForDevice();
    });
    
    navigator.xr.addEventListener('sessionend', () => {
      updateStatus();
      updateUIForDevice();
    });
  }
});

// Handle window resize
// 处理窗口尺寸变化
window.addEventListener('resize', updateUIForDevice);

// Switch between desktop and VR views
// 在桌面视图与 VR 视图间切换
function switchToVrView() {
  const desktopInterface = document.getElementById('desktopInterface');
  prefersVrView = true;
  desktopInterface.style.display = 'none';
  // The VR start button should already be visible or will be created by vr_app.js
  // VR 开始按钮应该已存在，或由 vr_app.js 创建
  // Trigger the button creation if not already done
  // 如果还没有创建，则触发创建逻辑
  if (!document.getElementById('start-tracking-button')) {
    // Create a simple fallback button for non-XR devices
    // 为不支持 XR 的设备创建一个简单的备用按钮
    createFallbackVrButton();
  }
  showBackToDesktopButton();
}

function switchToDesktopView() {
  const desktopInterface = document.getElementById('desktopInterface');
  prefersVrView = false;
  desktopInterface.style.display = 'block';
  hideBackToDesktopButton();
}

function showBackToDesktopButton() {
  let backBtn = document.getElementById('back-to-desktop-button');
  if (!backBtn) {
    backBtn = document.createElement('button');
    backBtn.id = 'back-to-desktop-button';
    backBtn.textContent = '← Back to Desktop View';
    backBtn.style.cssText = `
      position: fixed;
      bottom: 20px;
      left: 50%;
      transform: translateX(-50%);
      padding: 12px 24px;
      font-size: 16px;
      background-color: #666;
      color: white;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      z-index: 9998;
      box-shadow: 0 4px 8px rgba(0,0,0,0.3);
    `;
    backBtn.onclick = switchToDesktopView;
    document.body.appendChild(backBtn);
  }
  backBtn.style.display = 'block';
}

function hideBackToDesktopButton() {
  const backBtn = document.getElementById('back-to-desktop-button');
  if (backBtn) {
    backBtn.style.display = 'none';
  }
}

function createFallbackVrButton() {
  // Also create the instructions panel if the function exists
  // 如果函数存在，也同时创建说明面板
  if (typeof createVrInstructionsPanel === 'function') {
    createVrInstructionsPanel();
  }

  const startButton = document.createElement('button');
  startButton.id = 'start-tracking-button';
  startButton.textContent = 'Start Controller Tracking';
  startButton.style.cssText = `
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    padding: 20px 40px;
    font-size: 20px;
    font-weight: bold;
    background-color: #4CAF50;
    color: white;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    z-index: 9999;
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
  `;
  startButton.onclick = async () => {
    const sceneEl = document.querySelector('a-scene');
    if (sceneEl) {
      startButton.textContent = 'Connecting...';
      startButton.disabled = true;
      try {
        // Check if robot is already connected
        // 检查机器人是否已连接
        const statusResponse = await fetch('/api/status');
        const status = await statusResponse.json();
        if (!status.robotEngaged) {
          startButton.textContent = 'Connecting Arms...';
          const connectResponse = await fetch('/api/robot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'connect' })
          });
          const connectResult = await connectResponse.json();
          if (!connectResult.success) {
            throw new Error(connectResult.error || 'Failed to connect robot arms');
          }
          await new Promise(resolve => setTimeout(resolve, 500));
        }
        startButton.textContent = 'Starting VR...';
        if (typeof enterImmersiveMode === 'function') {
          await enterImmersiveMode(sceneEl);
        } else {
          throw new Error('VR entry helper not loaded');
        }
      } catch (err) {
        alert(`Failed to start: ${err.message}`);
        startButton.textContent = 'Start Controller Tracking';
        startButton.disabled = false;
      }
    } else {
      alert('VR scene not available. Please reload the page.');
    }
  };
  document.body.appendChild(startButton);
} 