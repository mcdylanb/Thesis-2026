%% Real-Time Dual-Anchor CSI Preprocessing & Visualization Engine
clear; clc; close all;

% --- CONFIGURATION PARAMETERS ---
windowSize = 150;       % Number of time-history packets to display on screen
numSubcarriers = 64;    % Standard expected subcarriers from your ESP32
smoothingSpan = 9;      % Moving average span for live noise reduction filter

% --- INITIALIZE ROLLING DATA BUFFERS ---
% Pre-allocating matrices ensures high frame rates without stuttering
buffer_A1_raw  = zeros(windowSize, numSubcarriers);
buffer_A1_filt = zeros(windowSize, numSubcarriers);
buffer_A2_raw  = zeros(windowSize, numSubcarriers);
buffer_A2_filt = zeros(windowSize, numSubcarriers);

% --- SETUP LIVE PLOTS (PRE-ALLOCATION) ---
fig = figure('Color', [1 1 1], 'Position', [100, 50, 1400, 850], 'Name', 'Live CSI Engine Pipeline');

% Subplot 1: Anchor 1 Raw Stream
subplot(2,2,1);
hHeat_A1_raw = imagesc(1:windowSize, 1:numSubcarriers, buffer_A1_raw');
colormap(gca, 'jet'); clim([0 60]); title('Anchor A1: RAW CSI Stream (Step 1)');
xlabel('Rolling Packet Window'); ylabel('Subcarrier'); set(gca, 'YDir', 'normal');

% Subplot 2: Anchor 1 Preprocessed Stream
subplot(2,2,3);
hHeat_A1_filt = imagesc(1:windowSize, 1:numSubcarriers, buffer_A1_filt');
colormap(gca, 'jet'); clim([0 60]); title('Anchor A1: CLEANED CSI (Dropped Zeros + Smoothed)');
xlabel('Rolling Packet Window'); ylabel('Subcarrier'); set(gca, 'YDir', 'normal');

% Subplot 3: Anchor 2 Raw Stream
subplot(2,2,2);
hHeat_A2_raw = imagesc(1:windowSize, 1:numSubcarriers, buffer_A2_raw');
colormap(gca, 'jet'); clim([0 60]); title('Anchor A2: RAW CSI Stream (Step 1)');
xlabel('Rolling Packet Window'); ylabel('Subcarrier'); set(gca, 'YDir', 'normal');

% Subplot 4: Anchor 2 Preprocessed Stream
subplot(2,2,4);
hHeat_A2_filt = imagesc(1:windowSize, 1:numSubcarriers, buffer_A2_filt');
colormap(gca, 'jet'); clim([0 60]); title('Anchor A2: CLEANED CSI (Dropped Zeros + Smoothed)');
xlabel('Rolling Packet Window'); ylabel('Subcarrier'); set(gca, 'YDir', 'normal');

%% --- OPEN NETWORKING UDP PORTS ---
fprintf('Opening network sockets... Make sure Python script is ready.\n');
try
    sock_A1 = udpport("LocalPort", 6001, "Timeout", 0.001);
    sock_A2 = udpport("LocalPort", 6002, "Timeout", 0.001);
catch ME
    error('Could not open ports. Make sure no other instances of MATLAB are running.');
end

cleanupObj = onCleanup(@()clear(['sock_A1', 'sock_A2']));
fprintf('Engine initialized. Listening live for ESP32 streams... Press Ctrl+C in command window to end.\n');

%% --- MAIN EXECUTION PIPELINE LOOP ---
while ishandle(fig)
    
    % --- PROCESS ANCHOR A1 DATA ---
    if sock_A1.NumBytesAvailable > 0
        dataStr = read(sock_A1, sock_A1.NumBytesAvailable, "string");
        % Extract the last complete packet in the socket queue
        lines = splitLines(dataStr);
        validLine = "";
        for idx = length(lines):-1:1
            if contains(lines(idx), "CSI,A1,")
                validLine = lines(idx);
                break;
            end
        end
        
        if validLine ~= ""
            % Parse components
            payload = extractAfter(validLine, "A1|");
            parts = split(payload, ",");
            if length(parts) >= 11
                rawAmplitudes = str2double(parts(11:end))';
                
                if length(rawAmplitudes) == numSubcarriers
                    % Shift buffer down and push raw data
                    buffer_A1_raw = [buffer_A1_raw(2:end, :); rawAmplitudes];
                    
                    % REALTIME PREPROCESSING PIPELINE
                    cleanedAmplitudes = rawAmplitudes;
                    % Step A: Interpolate/Drop out your Null Subcarrier Zeros (indices 28-38)
                    nullIdxs = (cleanedAmplitudes == 0);
                    if any(nullIdxs)
                        cleanedAmplitudes(nullIdxs) = mean(cleanedAmplitudes(~nullIdxs)); 
                    end
                    buffer_A1_filt = [buffer_A1_filt(2:end, :); cleanedAmplitudes];
                    
                    % Step B: Apply moving window filter across time dimension
                    buffer_A1_filt = movmean(buffer_A1_filt, smoothingSpan, 1);
                    
                    % Update Graph Graphics Objects Directly (Saves massive processing time)
                    set(hHeat_A1_raw, 'CData', buffer_A1_raw');
                    set(hHeat_A1_filt, 'CData', buffer_A1_filt');
                end
            end
        end
    end
    
    % --- PROCESS ANCHOR A2 DATA ---
    if sock_A2.NumBytesAvailable > 0
        dataStr = read(sock_A2, sock_A2.NumBytesAvailable, "string");
        lines = splitLines(dataStr);
        validLine = "";
        for idx = length(lines):-1:1
            if contains(lines(idx), "CSI,A2,")
                validLine = lines(idx);
                break;
            end
        end
        
        if validLine ~= ""
            payload = extractAfter(validLine, "A2|");
            parts = split(payload, ",");
            if length(parts) >= 11
                rawAmplitudes = str2double(parts(11:end))';
                
                if length(rawAmplitudes) == numSubcarriers
                    buffer_A2_raw = [buffer_A2_raw(2:end, :); rawAmplitudes];
                    
                    % REALTIME PREPROCESSING PIPELINE
                    cleanedAmplitudes = rawAmplitudes;
                    nullIdxs = (cleanedAmplitudes == 0);
                    if any(nullIdxs)
                        cleanedAmplitudes(nullIdxs) = mean(cleanedAmplitudes(~nullIdxs));
                    end
                    buffer_A2_filt = [buffer_A2_filt(2:end, :); cleanedAmplitudes];
                    buffer_A2_filt = movmean(buffer_A2_filt, smoothingSpan, 1);
                    
                    set(hHeat_A2_raw, 'CData', buffer_A2_raw');
                    set(hHeat_A2_filt, 'CData', buffer_A2_filt');
                end
            end
        end
    end
    
    % Flush graphics commands to the monitor efficiently
    drawnow limitrate;
end
