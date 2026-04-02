// Wait for A-Frame scene to load
// 等待 A-Frame 场景加载完成

AFRAME.registerComponent('controller-updater', {
  init: function () {
    console.log("Controller updater component initialized.");
    // Controllers are enabled
    // 控制器已启用

    this.leftHand = document.querySelector('#leftHand');
    this.rightHand = document.querySelector('#rightHand');
    this.leftHandInfoText = document.querySelector('#leftHandInfo');
    this.rightHandInfoText = document.querySelector('#rightHandInfo');

    // --- WebSocket Setup ---
    // --- WebSocket 设置 ---
    this.websocket = null;
    this.leftGripDown = false;
    this.rightGripDown = false;
    this.leftTriggerDown = false;
    this.rightTriggerDown = false;

    // --- Status reporting ---
    // --- 状态上报 ---
    this.lastStatusUpdate = 0;
    this.statusUpdateInterval = 5000; // 5 seconds

    // --- Relative rotation tracking ---
    // --- 相对旋转跟踪 ---
    this.leftGripInitialRotation = null;
    this.rightGripInitialRotation = null;
    this.leftRelativeRotation = { x: 0, y: 0, z: 0 };
    this.rightRelativeRotation = { x: 0, y: 0, z: 0 };

    // --- Quaternion-based Z-axis rotation tracking ---
    // --- 基于四元数的 Z 轴旋转跟踪 ---
    this.leftGripInitialQuaternion = null;
    this.rightGripInitialQuaternion = null;
    this.leftZAxisRotation = 0;
    this.rightZAxisRotation = 0;

    // --- Get hostname dynamically ---
    // --- 动态获取主机名 ---
    const serverHostname = window.location.hostname;
    // 确保这里与 controller_server.py 中的端口一致
    const websocketPort = 8442; // Make sure this matches controller_server.py
    const websocketUrl = `wss://${serverHostname}:${websocketPort}`;
    console.log(`Attempting WebSocket connection to: ${websocketUrl}`);
    // !!! IMPORTANT: Replace 'YOUR_LAPTOP_IP' with the actual IP address of your laptop !!!
    // !!! 重要：将 'YOUR_LAPTOP_IP' 替换为你笔记本电脑的实际 IP 地址 !!!
    // const websocketUrl = 'ws://YOUR_LAPTOP_IP:8442';
    // 示例：将 websocketUrl 改为指向你笔记本电脑 IP 的 ws 地址
    try {
      this.websocket = new WebSocket(websocketUrl);
      this.websocket.onopen = (event) => {
        console.log(`WebSocket connected to ${websocketUrl}`);
        this.reportVRStatus(true);
      };
      this.websocket.onerror = (event) => {
        // More detailed error logging
        // 输出更详细的错误日志
        console.error(`WebSocket Error: Event type: ${event.type}`, event);
        this.reportVRStatus(false);
      };
      this.websocket.onclose = (event) => {
        console.log(`WebSocket disconnected from ${websocketUrl}. Clean close: ${event.wasClean}, Code: ${event.code}, Reason: '${event.reason}'`);
        // Attempt to log specific error if available (might be limited by browser security)
        // 如果可用则尝试记录更具体的错误信息（可能受浏览器安全限制）
        if (!event.wasClean) {
          console.error('WebSocket closed unexpectedly.');
        }
        // 清除引用
        this.websocket = null; // Clear the reference
        this.reportVRStatus(false);
      };
      this.websocket.onmessage = (event) => {
        // 记录服务器发来的任何消息
        console.log(`WebSocket message received: ${event.data}`); // Log any messages from server
      };
    } catch (error) {
        console.error(`Failed to create WebSocket connection to ${websocketUrl}:`, error);
        this.reportVRStatus(false);
    }
    // --- End WebSocket Setup ---
    // --- WebSocket 设置结束 ---

    // --- VR Status Reporting Function ---
    // --- VR 状态上报函数 ---
    this.reportVRStatus = (connected) => {
      // Update global status if available (for desktop interface)
      // 如果可用，则更新全局状态（供桌面界面使用）
      if (typeof updateStatus === 'function') {
        updateStatus({ vrConnected: connected });
      }
      
      // Also try to notify parent window if in iframe
      // 如果当前在 iframe 中，也尝试通知父窗口
      try {
        if (window.parent && window.parent !== window) {
          window.parent.postMessage({
            type: 'vr_status',
            connected: connected
          }, '*');
        }
      } catch (e) {
        // Ignore cross-origin errors
        // 忽略跨域错误
      }
    };

    if (!this.leftHand || !this.rightHand || !this.leftHandInfoText || !this.rightHandInfoText) {
      console.error("Controller or text entities not found!");
      // Check which specific elements are missing
      // 检查具体缺少哪些元素
      if (!this.leftHand) console.error("Left hand entity not found");
      if (!this.rightHand) console.error("Right hand entity not found");
      if (!this.leftHandInfoText) console.error("Left hand info text not found");
      if (!this.rightHandInfoText) console.error("Right hand info text not found");
      return;
    }

    // Apply initial rotation to combined text elements
    // 给组合文本元素应用初始旋转
    // 绕 X 轴旋转 -90 度
    const textRotation = '-90 0 0'; // Rotate -90 degrees around X-axis
    if (this.leftHandInfoText) this.leftHandInfoText.setAttribute('rotation', textRotation);
    if (this.rightHandInfoText) this.rightHandInfoText.setAttribute('rotation', textRotation);

    // --- Create axis indicators ---
    // --- 创建坐标轴指示器 ---
    this.createAxisIndicators();

    // --- Helper function to send grip release message ---
    // --- 发送 grip 松开消息的辅助函数 ---
    this.sendGripRelease = (hand) => {
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        const releaseMessage = {
          hand: hand,
          gripReleased: true
        };
        this.websocket.send(JSON.stringify(releaseMessage));
        console.log(`Sent grip release for ${hand} hand`);
      }
    };

    // --- Helper function to send trigger release message ---
    // --- 发送 trigger 松开消息的辅助函数 ---
    this.sendTriggerRelease = (hand) => {
      if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        const releaseMessage = {
          hand: hand,
          triggerReleased: true
        };
        this.websocket.send(JSON.stringify(releaseMessage));
        console.log(`Sent trigger release for ${hand} hand`);
      }
    };

    // --- Helper function to calculate relative rotation ---
    // --- 计算相对旋转的辅助函数 ---
    this.calculateRelativeRotation = (currentRotation, initialRotation) => {
      return {
        x: currentRotation.x - initialRotation.x,
        y: currentRotation.y - initialRotation.y,
        z: currentRotation.z - initialRotation.z
      };
    };

    // --- Helper function to calculate Z-axis rotation from quaternions ---
    // --- 根据四元数计算 Z 轴旋转的辅助函数 ---
    this.calculateZAxisRotation = (currentQuaternion, initialQuaternion) => {
      // Calculate relative quaternion (from initial to current)
      // 计算相对四元数（从初始姿态到当前姿态）
      const relativeQuat = new THREE.Quaternion();
      relativeQuat.multiplyQuaternions(currentQuaternion, initialQuaternion.clone().invert());
      
      // Get the controller's current forward direction (local Z-axis in world space)
      // 获取控制器当前的前向方向（世界坐标系中的本地 Z 轴）
      const forwardDirection = new THREE.Vector3(0, 0, 1);
      forwardDirection.applyQuaternion(currentQuaternion);
      
      // Convert relative quaternion to axis-angle representation
      // 将相对四元数转换为轴角表示
      const angle = 2 * Math.acos(Math.abs(relativeQuat.w));
      
      // Handle case where there's no rotation (avoid division by zero)
      // 处理没有旋转的情况（避免除以零）
      if (angle < 0.0001) {
        return 0;
      }
      
      // Get the rotation axis
      // 获取旋转轴
      const sinHalfAngle = Math.sqrt(1 - relativeQuat.w * relativeQuat.w);
      const rotationAxis = new THREE.Vector3(
        relativeQuat.x / sinHalfAngle,
        relativeQuat.y / sinHalfAngle,
        relativeQuat.z / sinHalfAngle
      );
      
      // Project the rotation axis onto the forward direction to get the component
      // of rotation around the forward axis
      // 将旋转轴投影到前向方向上，得到绕前向轴旋转的分量
      const projectedComponent = rotationAxis.dot(forwardDirection);
      
      // The rotation around the forward axis is the angle times the projection
      // 绕前向轴的旋转量等于旋转角乘以该投影分量
      const forwardRotation = angle * projectedComponent;
      
      // Convert to degrees and handle the sign properly
      // 转换为角度，并正确处理符号
      let degrees = THREE.MathUtils.radToDeg(forwardRotation);
      
      // Normalize to -180 to +180 range to avoid sudden jumps
      // 归一化到 -180 到 +180 范围，避免数值突变
      while (degrees > 180) degrees -= 360;
      while (degrees < -180) degrees += 360;
      
      return degrees;
    };

    // --- Modify Event Listeners ---
    // --- 修改事件监听器 ---
    this.leftHand.addEventListener('triggerdown', (evt) => {
        console.log('Left Trigger Pressed');
        this.leftTriggerDown = true;
    });
    this.leftHand.addEventListener('triggerup', (evt) => {
        console.log('Left Trigger Released');
        this.leftTriggerDown = false;
        // 发送 trigger 松开消息
        this.sendTriggerRelease('left'); // Send trigger release message
    });
    this.leftHand.addEventListener('gripdown', (evt) => {
        console.log('Left Grip Pressed');
        // 设置 grip 状态
        this.leftGripDown = true; // Set grip state
        
        // Store initial rotation for relative tracking
        // 保存初始旋转，用于相对旋转跟踪
        if (this.leftHand.object3D.visible) {
          const leftRotEuler = this.leftHand.object3D.rotation;
          this.leftGripInitialRotation = {
            x: THREE.MathUtils.radToDeg(leftRotEuler.x),
            y: THREE.MathUtils.radToDeg(leftRotEuler.y),
            z: THREE.MathUtils.radToDeg(leftRotEuler.z)
          };
          
          // Store initial quaternion for Z-axis rotation tracking
          // 保存初始四元数，用于 Z 轴旋转跟踪
          this.leftGripInitialQuaternion = this.leftHand.object3D.quaternion.clone();
          
          console.log('Left grip initial rotation:', this.leftGripInitialRotation);
          console.log('Left grip initial quaternion:', this.leftGripInitialQuaternion);
        }
    });
    // 添加 gripup 监听器
    this.leftHand.addEventListener('gripup', (evt) => { // Add gripup listener
        console.log('Left Grip Released');
        // 重置 grip 状态
        this.leftGripDown = false; // Reset grip state
        // 重置初始旋转
        this.leftGripInitialRotation = null; // Reset initial rotation
        // 重置初始四元数
        this.leftGripInitialQuaternion = null; // Reset initial quaternion
        // 重置相对旋转
        this.leftRelativeRotation = { x: 0, y: 0, z: 0 }; // Reset relative rotation
        // 重置 Z 轴旋转
        this.leftZAxisRotation = 0; // Reset Z-axis rotation
        // 发送 grip 松开消息
        this.sendGripRelease('left'); // Send grip release message
    });

    this.rightHand.addEventListener('triggerdown', (evt) => {
        console.log('Right Trigger Pressed');
        this.rightTriggerDown = true;
    });
    this.rightHand.addEventListener('triggerup', (evt) => {
        console.log('Right Trigger Released');
        this.rightTriggerDown = false;
        // 发送 trigger 松开消息
        this.sendTriggerRelease('right'); // Send trigger release message
    });
    this.rightHand.addEventListener('gripdown', (evt) => {
        console.log('Right Grip Pressed');
        // 设置 grip 状态
        this.rightGripDown = true; // Set grip state
        
        // Store initial rotation for relative tracking
        // 保存初始旋转，用于相对旋转跟踪
        if (this.rightHand.object3D.visible) {
          const rightRotEuler = this.rightHand.object3D.rotation;
          this.rightGripInitialRotation = {
            x: THREE.MathUtils.radToDeg(rightRotEuler.x),
            y: THREE.MathUtils.radToDeg(rightRotEuler.y),
            z: THREE.MathUtils.radToDeg(rightRotEuler.z)
          };
          
          // Store initial quaternion for Z-axis rotation tracking
          // 保存初始四元数，用于 Z 轴旋转跟踪
          this.rightGripInitialQuaternion = this.rightHand.object3D.quaternion.clone();
          
          console.log('Right grip initial rotation:', this.rightGripInitialRotation);
          console.log('Right grip initial quaternion:', this.rightGripInitialQuaternion);
        }
    });
    // 添加 gripup 监听器
    this.rightHand.addEventListener('gripup', (evt) => { // Add gripup listener
        console.log('Right Grip Released');
        // 重置 grip 状态
        this.rightGripDown = false; // Reset grip state
        // 重置初始旋转
        this.rightGripInitialRotation = null; // Reset initial rotation
        // 重置初始四元数
        this.rightGripInitialQuaternion = null; // Reset initial quaternion
        // 重置相对旋转
        this.rightRelativeRotation = { x: 0, y: 0, z: 0 }; // Reset relative rotation
        // 重置 Z 轴旋转
        this.rightZAxisRotation = 0; // Reset Z-axis rotation
        // 发送 grip 松开消息
        this.sendGripRelease('right'); // Send grip release message
    });
    // --- End Modify Event Listeners ---
    // --- 事件监听器修改结束 ---

  },

  createAxisIndicators: function() {
    // Create XYZ axis indicators for both controllers
    // 为两个控制器创建 XYZ 坐标轴指示器
    
    // Left Controller Axes
    // 左手控制器坐标轴
    // X-axis (Red)
    // X 轴（红色）
    const leftXAxis = document.createElement('a-cylinder');
    leftXAxis.setAttribute('id', 'leftXAxis');
    leftXAxis.setAttribute('height', '0.08');
    leftXAxis.setAttribute('radius', '0.003');
    // X 轴使用红色
    leftXAxis.setAttribute('color', '#ff0000'); // Red for X
    leftXAxis.setAttribute('position', '0.04 0 0');
    // 旋转到沿 X 轴指向
    leftXAxis.setAttribute('rotation', '0 0 90'); // Rotate to point along X-axis
    this.leftHand.appendChild(leftXAxis);

    const leftXTip = document.createElement('a-cone');
    leftXTip.setAttribute('height', '0.015');
    leftXTip.setAttribute('radius-bottom', '0.008');
    leftXTip.setAttribute('radius-top', '0');
    leftXTip.setAttribute('color', '#ff0000');
    leftXTip.setAttribute('position', '0.055 0 0');
    leftXTip.setAttribute('rotation', '0 0 90');
    this.leftHand.appendChild(leftXTip);

    // Y-axis (Green) - Up
    // Y 轴（绿色）- 向上
    const leftYAxis = document.createElement('a-cylinder');
    leftYAxis.setAttribute('id', 'leftYAxis');
    leftYAxis.setAttribute('height', '0.08');
    leftYAxis.setAttribute('radius', '0.003');
    // Y 轴使用绿色
    leftYAxis.setAttribute('color', '#00ff00'); // Green for Y
    leftYAxis.setAttribute('position', '0 0.04 0');
    // 默认朝上方向
    leftYAxis.setAttribute('rotation', '0 0 0'); // Default up orientation
    this.leftHand.appendChild(leftYAxis);

    const leftYTip = document.createElement('a-cone');
    leftYTip.setAttribute('height', '0.015');
    leftYTip.setAttribute('radius-bottom', '0.008');
    leftYTip.setAttribute('radius-top', '0');
    leftYTip.setAttribute('color', '#00ff00');
    leftYTip.setAttribute('position', '0 0.055 0');
    this.leftHand.appendChild(leftYTip);

    // Z-axis (Blue) - Forward
    // Z 轴（蓝色）- 向前
    const leftZAxis = document.createElement('a-cylinder');
    leftZAxis.setAttribute('id', 'leftZAxis');
    leftZAxis.setAttribute('height', '0.08');
    leftZAxis.setAttribute('radius', '0.003');
    // Z 轴使用蓝色
    leftZAxis.setAttribute('color', '#0000ff'); // Blue for Z
    leftZAxis.setAttribute('position', '0 0 0.04');
    // 旋转到沿 Z 轴指向
    leftZAxis.setAttribute('rotation', '90 0 0'); // Rotate to point along Z-axis
    this.leftHand.appendChild(leftZAxis);

    const leftZTip = document.createElement('a-cone');
    leftZTip.setAttribute('height', '0.015');
    leftZTip.setAttribute('radius-bottom', '0.008');
    leftZTip.setAttribute('radius-top', '0');
    leftZTip.setAttribute('color', '#0000ff');
    leftZTip.setAttribute('position', '0 0 0.055');
    leftZTip.setAttribute('rotation', '90 0 0');
    this.leftHand.appendChild(leftZTip);

    // Right Controller Axes
    // 右手控制器坐标轴
    // X-axis (Red)
    // X 轴（红色）
    const rightXAxis = document.createElement('a-cylinder');
    rightXAxis.setAttribute('id', 'rightXAxis');
    rightXAxis.setAttribute('height', '0.08');
    rightXAxis.setAttribute('radius', '0.003');
    // X 轴使用红色
    rightXAxis.setAttribute('color', '#ff0000'); // Red for X
    rightXAxis.setAttribute('position', '0.04 0 0');
    // 旋转到沿 X 轴指向
    rightXAxis.setAttribute('rotation', '0 0 90'); // Rotate to point along X-axis
    this.rightHand.appendChild(rightXAxis);

    const rightXTip = document.createElement('a-cone');
    rightXTip.setAttribute('height', '0.015');
    rightXTip.setAttribute('radius-bottom', '0.008');
    rightXTip.setAttribute('radius-top', '0');
    rightXTip.setAttribute('color', '#ff0000');
    rightXTip.setAttribute('position', '0.055 0 0');
    rightXTip.setAttribute('rotation', '0 0 90');
    this.rightHand.appendChild(rightXTip);

    // Y-axis (Green) - Up
    // Y 轴（绿色）- 向上
    const rightYAxis = document.createElement('a-cylinder');
    rightYAxis.setAttribute('id', 'rightYAxis');
    rightYAxis.setAttribute('height', '0.08');
    rightYAxis.setAttribute('radius', '0.003');
    // Y 轴使用绿色
    rightYAxis.setAttribute('color', '#00ff00'); // Green for Y
    rightYAxis.setAttribute('position', '0 0.04 0');
    // 默认朝上方向
    rightYAxis.setAttribute('rotation', '0 0 0'); // Default up orientation
    this.rightHand.appendChild(rightYAxis);

    const rightYTip = document.createElement('a-cone');
    rightYTip.setAttribute('height', '0.015');
    rightYTip.setAttribute('radius-bottom', '0.008');
    rightYTip.setAttribute('radius-top', '0');
    rightYTip.setAttribute('color', '#00ff00');
    rightYTip.setAttribute('position', '0 0.055 0');
    this.rightHand.appendChild(rightYTip);

    // Z-axis (Blue) - Forward
    // Z 轴（蓝色）- 向前
    const rightZAxis = document.createElement('a-cylinder');
    rightZAxis.setAttribute('id', 'rightZAxis');
    rightZAxis.setAttribute('height', '0.08');
    rightZAxis.setAttribute('radius', '0.003');
    // Z 轴使用蓝色
    rightZAxis.setAttribute('color', '#0000ff'); // Blue for Z
    rightZAxis.setAttribute('position', '0 0 0.04');
    // 旋转到沿 Z 轴指向
    rightZAxis.setAttribute('rotation', '90 0 0'); // Rotate to point along Z-axis
    this.rightHand.appendChild(rightZAxis);

    const rightZTip = document.createElement('a-cone');
    rightZTip.setAttribute('height', '0.015');
    rightZTip.setAttribute('radius-bottom', '0.008');
    rightZTip.setAttribute('radius-top', '0');
    rightZTip.setAttribute('color', '#0000ff');
    rightZTip.setAttribute('position', '0 0 0.055');
    rightZTip.setAttribute('rotation', '90 0 0');
    this.rightHand.appendChild(rightZTip);

    console.log('XYZ axis indicators created for both controllers (RGB for XYZ)');
  },

  tick: function () {
    // Update controller text if controllers are visible
    // 如果控制器可见，则更新控制器文本
    // 增加安全检查
    if (!this.leftHand || !this.rightHand) return; // Added safety check

    // --- BEGIN DETAILED LOGGING ---
    // --- 开始详细日志 ---
    if (this.leftHand.object3D) {
      // console.log(`Left Hand Raw - Visible: ${this.leftHand.object3D.visible}, Pos: ${this.leftHand.object3D.position.x.toFixed(2)},${this.leftHand.object3D.position.y.toFixed(2)},${this.leftHand.object3D.position.z.toFixed(2)}`);
      // 左手原始数据日志：可见性与位置
    }
    if (this.rightHand.object3D) {
      // console.log(`Right Hand Raw - Visible: ${this.rightHand.object3D.visible}, Pos: ${this.rightHand.object3D.position.x.toFixed(2)},${this.rightHand.object3D.position.y.toFixed(2)},${this.rightHand.object3D.position.z.toFixed(2)}`);
      // 右手原始数据日志：可见性与位置
    }
    // --- END DETAILED LOGGING ---
    // --- 结束详细日志 ---

    // Collect data from both controllers
    // 收集两个控制器的数据
    const leftController = {
        hand: 'left',
        position: null,
        rotation: null,
        gripActive: false,
        trigger: 0
    };
    
    const rightController = {
        hand: 'right',
        position: null,
        rotation: null,
        gripActive: false,
        trigger: 0
    };

    // Update Left Hand Text & Collect Data
    // 更新左手文本并收集数据
    if (this.leftHand.object3D.visible) {
        const leftPos = this.leftHand.object3D.position;
        // 欧拉角，单位为弧度
        const leftRotEuler = this.leftHand.object3D.rotation; // Euler angles in radians
        // Convert to degrees without offset
        // 转换为角度，不加偏移
        const leftRotX = THREE.MathUtils.radToDeg(leftRotEuler.x);
        const leftRotY = THREE.MathUtils.radToDeg(leftRotEuler.y);
        const leftRotZ = THREE.MathUtils.radToDeg(leftRotEuler.z);

        // Calculate relative rotation if grip is held
        // 如果 grip 按住，则计算相对旋转
        if (this.leftGripDown && this.leftGripInitialRotation) {
          this.leftRelativeRotation = this.calculateRelativeRotation(
            { x: leftRotX, y: leftRotY, z: leftRotZ },
            this.leftGripInitialRotation
          );
          
          // Calculate Z-axis rotation using quaternions
          // 使用四元数计算 Z 轴旋转
          if (this.leftGripInitialQuaternion) {
            this.leftZAxisRotation = this.calculateZAxisRotation(
              this.leftHand.object3D.quaternion,
              this.leftGripInitialQuaternion
            );
          }
          
          console.log('Left relative rotation:', this.leftRelativeRotation);
          console.log('Left Z-axis rotation:', this.leftZAxisRotation.toFixed(1), 'degrees');
        }

        // Create display text including relative rotation when grip is held
        // 在 grip 按住时，创建包含相对旋转信息的显示文本
        let combinedLeftText = `Pos: ${leftPos.x.toFixed(2)} ${leftPos.y.toFixed(2)} ${leftPos.z.toFixed(2)}\\nRot: ${leftRotX.toFixed(0)} ${leftRotY.toFixed(0)} ${leftRotZ.toFixed(0)}`;
        if (this.leftGripDown && this.leftGripInitialRotation) {
          combinedLeftText += `\\nZ-Rot: ${this.leftZAxisRotation.toFixed(1)}°`;
        }

        if (this.leftHandInfoText) {
            this.leftHandInfoText.setAttribute('value', combinedLeftText);
        }

        // Collect left controller data
        // 收集左手控制器数据
        leftController.position = { x: leftPos.x, y: leftPos.y, z: leftPos.z };
        leftController.rotation = { x: leftRotX, y: leftRotY, z: leftRotZ };
        leftController.quaternion = { 
          x: this.leftHand.object3D.quaternion.x, 
          y: this.leftHand.object3D.quaternion.y, 
          z: this.leftHand.object3D.quaternion.z, 
          w: this.leftHand.object3D.quaternion.w 
        };
        leftController.trigger = this.leftTriggerDown ? 1 : 0;
        leftController.gripActive = this.leftGripDown;
    }

    // Update Right Hand Text & Collect Data
    // 更新右手文本并收集数据
    if (this.rightHand.object3D.visible) {
        const rightPos = this.rightHand.object3D.position;
        // 欧拉角，单位为弧度
        const rightRotEuler = this.rightHand.object3D.rotation; // Euler angles in radians
        // Convert to degrees without offset
        // 转换为角度，不加偏移
        const rightRotX = THREE.MathUtils.radToDeg(rightRotEuler.x);
        const rightRotY = THREE.MathUtils.radToDeg(rightRotEuler.y);
        const rightRotZ = THREE.MathUtils.radToDeg(rightRotEuler.z);

        // Calculate relative rotation if grip is held
        // 如果 grip 按住，则计算相对旋转
        if (this.rightGripDown && this.rightGripInitialRotation) {
          this.rightRelativeRotation = this.calculateRelativeRotation(
            { x: rightRotX, y: rightRotY, z: rightRotZ },
            this.rightGripInitialRotation
          );
          
          // Calculate Z-axis rotation using quaternions
          // 使用四元数计算 Z 轴旋转
          if (this.rightGripInitialQuaternion) {
            this.rightZAxisRotation = this.calculateZAxisRotation(
              this.rightHand.object3D.quaternion,
              this.rightGripInitialQuaternion
            );
          }
          
          console.log('Right relative rotation:', this.rightRelativeRotation);
          console.log('Right Z-axis rotation:', this.rightZAxisRotation.toFixed(1), 'degrees');
        }

        // Create display text including relative rotation when grip is held
        // 在 grip 按住时，创建包含相对旋转信息的显示文本
        let combinedRightText = `Pos: ${rightPos.x.toFixed(2)} ${rightPos.y.toFixed(2)} ${rightPos.z.toFixed(2)}\\nRot: ${rightRotX.toFixed(0)} ${rightRotY.toFixed(0)} ${rightRotZ.toFixed(0)}`;
        if (this.rightGripDown && this.rightGripInitialRotation) {
          combinedRightText += `\\nZ-Rot: ${this.rightZAxisRotation.toFixed(1)}°`;
        }

        if (this.rightHandInfoText) {
            this.rightHandInfoText.setAttribute('value', combinedRightText);
        }

        // Collect right controller data
        // 收集右手控制器数据
        rightController.position = { x: rightPos.x, y: rightPos.y, z: rightPos.z };
        rightController.rotation = { x: rightRotX, y: rightRotY, z: rightRotZ };
        rightController.quaternion = { 
          x: this.rightHand.object3D.quaternion.x, 
          y: this.rightHand.object3D.quaternion.y, 
          z: this.rightHand.object3D.quaternion.z, 
          w: this.rightHand.object3D.quaternion.w 
        };
        rightController.trigger = this.rightTriggerDown ? 1 : 0;
        rightController.gripActive = this.rightGripDown;
    }

    // Send combined packet if WebSocket is open and at least one controller has valid data
    // 如果 WebSocket 已打开且至少有一个控制器数据有效，则发送组合数据包
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        const hasValidLeft = leftController.position && (leftController.position.x !== 0 || leftController.position.y !== 0 || leftController.position.z !== 0);
        const hasValidRight = rightController.position && (rightController.position.x !== 0 || rightController.position.y !== 0 || rightController.position.z !== 0);
        
        if (hasValidLeft || hasValidRight) {
            const dualControllerData = {
                timestamp: Date.now(),
                leftController: leftController,
                rightController: rightController
            };
            this.websocket.send(JSON.stringify(dualControllerData));
        }
    }
  }
});


// Add the component to the scene after it's loaded
// 在场景加载完成后将组件添加到场景中
document.addEventListener('DOMContentLoaded', (event) => {
    const scene = document.querySelector('a-scene');

    if (scene) {
        // Listen for controller connection events
        // 监听控制器连接事件
        scene.addEventListener('controllerconnected', (evt) => {
            console.log('Controller CONNECTED:', evt.detail.name, evt.detail.component.data.hand);
        });
        scene.addEventListener('controllerdisconnected', (evt) => {
            console.log('Controller DISCONNECTED:', evt.detail.name, evt.detail.component.data.hand);
        });

        // Add controller-updater component when scene is loaded (A-Frame manages session)
        // 场景加载完成后添加 controller-updater 组件（会话由 A-Frame 管理）
        if (scene.hasLoaded) {
            scene.setAttribute('controller-updater', '');
            console.log("controller-updater component added immediately.");
        } else {
            scene.addEventListener('loaded', () => {
                scene.setAttribute('controller-updater', '');
                console.log("controller-updater component added after scene loaded.");
            });
        }
    } else {
        console.error('A-Frame scene not found!');
    }

    // Add controller tracking button logic
    // 添加控制器跟踪按钮逻辑
    addControllerTrackingButton();
});

function addControllerTrackingButton() {
    if (navigator.xr) {
        // Check for either immersive-ar (Quest 3/Pro) or immersive-vr (Quest 2)
        // 检查是否支持 immersive-ar（Quest 3/Pro）或 immersive-vr（Quest 2）
        Promise.all([
            navigator.xr.isSessionSupported('immersive-ar').catch(() => false),
            navigator.xr.isSessionSupported('immersive-vr').catch(() => false)
        ]).then(([arSupported, vrSupported]) => {
            if (arSupported || vrSupported) {
                // Create Start Controller Tracking button
                // 创建“开始控制器跟踪”按钮
                const startButton = document.createElement('button');
                startButton.id = 'start-tracking-button';
                startButton.textContent = 'Start Controller Tracking';
                startButton.style.position = 'fixed';
                startButton.style.top = '50%';
                startButton.style.left = '50%';
                startButton.style.transform = 'translate(-50%, -50%)';
                startButton.style.padding = '20px 40px';
                startButton.style.fontSize = '20px';
                startButton.style.fontWeight = 'bold';
                startButton.style.backgroundColor = '#4CAF50';
                startButton.style.color = 'white';
                startButton.style.border = 'none';
                startButton.style.borderRadius = '8px';
                startButton.style.cursor = 'pointer';
                startButton.style.zIndex = '9999';
                startButton.style.boxShadow = '0 4px 8px rgba(0,0,0,0.3)';
                startButton.style.transition = 'all 0.3s ease';

                // Hover effects
                // 悬停效果
                startButton.addEventListener('mouseenter', () => {
                    startButton.style.backgroundColor = '#45a049';
                    startButton.style.transform = 'translate(-50%, -50%) scale(1.05)';
                });
                startButton.addEventListener('mouseleave', () => {
                    startButton.style.backgroundColor = '#4CAF50';
                    startButton.style.transform = 'translate(-50%, -50%) scale(1)';
                });

                startButton.onclick = async () => {
                    console.log('Start Controller Tracking button clicked.');
                    const sceneEl = document.querySelector('a-scene');
                    if (!sceneEl) {
                        console.error('A-Frame scene not found for enterVR call!');
                        return;
                    }

                    // Update button to show we're connecting
                    // 更新按钮状态，显示正在连接
                    startButton.textContent = 'Connecting...';
                    startButton.disabled = true;

                    try {
                        // Check if robot is already connected
                        // 检查机器人是否已连接
                        const statusResponse = await fetch('/api/status');
                        const status = await statusResponse.json();

                        if (!status.robotEngaged) {
                            console.log('Robot not connected. Connecting arms first...');
                            startButton.textContent = 'Connecting Arms...';

                            // Connect the robot arms
                            // 连接机器人双臂
                            const connectResponse = await fetch('/api/robot', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json'
                                },
                                body: JSON.stringify({ action: 'connect' })
                            });
                            const connectResult = await connectResponse.json();

                            if (!connectResult.success) {
                                throw new Error(connectResult.error || 'Failed to connect robot arms');
                            }
                            console.log('Robot arms connected successfully.');

                            // Wait a moment for arms to initialize
                            // 稍等片刻，让机械臂完成初始化
                            await new Promise(resolve => setTimeout(resolve, 500));
                        } else {
                            console.log('Robot already connected.');
                        }

                        // Now enter VR mode
                        // 现在进入 VR 模式
                        console.log('Requesting VR session via A-Frame...');
                        startButton.textContent = 'Starting VR...';
                        await sceneEl.enterVR(true);
                    } catch (err) {
                        console.error('Failed to start controller tracking:', err);
                        alert(`Failed to start: ${err.message}`);
                        // Reset button state
                        // 重置按钮状态
                        startButton.textContent = 'Start Controller Tracking';
                        startButton.disabled = false;
                    }
                };

                document.body.appendChild(startButton);
                console.log('Official "Start Controller Tracking" button added.');

                // Add VR instructions panel
                // 添加 VR 说明面板
                createVrInstructionsPanel();

                // Show the back to desktop button (function defined in interface.js)
                // 显示返回桌面按钮（函数定义在 interface.js 中）
                if (typeof showBackToDesktopButton === 'function') {
                    showBackToDesktopButton();
                }

                // Listen for VR session events to hide/show start button
                // 监听 VR 会话事件以隐藏或显示开始按钮
                const sceneEl = document.querySelector('a-scene');
                if (sceneEl) {
                    sceneEl.addEventListener('enter-vr', () => {
                        console.log('Entered VR - hiding start button');
                        startButton.style.display = 'none';
                    });

                    sceneEl.addEventListener('exit-vr', () => {
                        console.log('Exited VR - showing start button');
                        startButton.style.display = 'block';
                    });
                }

            } else {
                console.warn('Neither immersive-ar nor immersive-vr supported by this browser/device.');
            }
        }).catch((err) => {
            console.error('Error checking XR support:', err);
        });
    } else {
        console.warn('WebXR not supported by this browser.');
    }
}

function createVrInstructionsPanel() {
    // Don't create if already exists
    // 如果已经存在则不要重复创建
    if (document.getElementById('vr-instructions-panel')) return;

    const panel = document.createElement('div');
    panel.id = 'vr-instructions-panel';
    panel.style.cssText = `
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        max-width: 90%;
        width: 600px;
        background: rgba(15, 52, 96, 0.95);
        border-radius: 12px;
        padding: 20px;
        color: white;
        z-index: 9998;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.1);
    `;

    panel.innerHTML = `
        <h2 style="margin: 0 0 15px 0; font-size: 1.2em; text-align: center;">VR Controller Instructions</h2>
        <div style="display: flex; gap: 15px; align-items: flex-start; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 150px; text-align: center;">
                <img src="media/telegrip_instructions.jpg" alt="VR Controller Instructions"
                     style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2);">
            </div>
            <div style="flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 8px; font-size: 14px;">
                <div style="padding: 8px; background: rgba(255,255,255,0.1); border-radius: 6px;">
                    <strong style="color: #ee4d9a;">Grip Button:</strong> Hold to move the arm
                </div>
                <div style="padding: 8px; background: rgba(255,255,255,0.1); border-radius: 6px;">
                    <strong style="color: #9af58c;">Trigger:</strong> Hold to close gripper
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(panel);

    // Hide panel when entering VR
    // 进入 VR 时隐藏面板
    const sceneEl = document.querySelector('a-scene');
    if (sceneEl) {
        sceneEl.addEventListener('enter-vr', () => {
            panel.style.display = 'none';
        });
        sceneEl.addEventListener('exit-vr', () => {
            panel.style.display = 'block';
        });
    }
} 