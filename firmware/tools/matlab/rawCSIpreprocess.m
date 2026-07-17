%% Step 1: Load the Structured CSV Table
[file, path] = uigetfile('*.csv', 'Select your Gateway Logger CSV File');
if isequal(file,0)
    disp('User selected Cancel');
    return;
end

% Read table preserving the python logger headers: host_iso, host_ns, line
opts = detectImportOptions(fullfile(path, file));
opts.VariableNamingRule = 'preserve';
data = readtable(fullfile(path, file), opts);

% Clean the string column
data.line = string(data.line);
csiRows = data(startsWith(data.line, "CSI,"), :);

%% Step 2: Robust Parsing & First-Line Correction
numRawPackets = height(csiRows);
parsedRSSI = zeros(numRawPackets, 1);
parsedTimestamps = csiRows.host_ns;
rawCSIList = cell(numRawPackets, 1);

for i = 1:numRawPackets
    % Clean up quotes if Python wrapped the line in them
    lineStr = strrep(csiRows.line(i), '"', '');
    parts = split(lineStr, ",");
    
    % Extract RSSI (Index 5)
    parsedRSSI(i) = str2double(parts(5));
    
    % Extract CSI amplitudes (Index 11 to the end)
    % Index 9 gives '64' (subcarrier count), Index 10 is '70', Index 11 starts the array
    rawCSIList{i} = str2double(parts(11:end))';
end

% DYNAMIC FILTERING: Find the standard packet length (mode)
% This automatically drops the corrupted first line because its length will be huge
lengths = cellfun(@length, rawCSIList);
standardLength = mode(lengths);
validIdx = (lengths == standardLength);

% Apply the filter to keep only perfectly uncorrupted packets
rssiArray = parsedRSSI(validIdx);
timeNsArray = parsedTimestamps(validIdx);
finalCSI = rawCSIList(validIdx);
csiMatrix = cat(1, finalCSI{:});
numValidPackets = sum(validIdx);

% Calculate precise elapsed time in seconds using host_ns
timeSeconds = double(timeNsArray - timeNsArray(1)) / 1e9;

%% Step 3: Command Window EDA Report
clc;
fprintf('=== THESIS EDA REPORT: RAW DATA INSPECTION ===\n');
fprintf('Total Rows Read from CSV:    %d\n', height(data));
fprintf('Valid Packets Retained:      %d\n', numValidPackets);
fprintf('Corrupted Rows Dropped:      %d\n', numRawPackets - numValidPackets);
fprintf('Detected Active Subcarriers: %d\n', standardLength);

% Timestamp continuity check
timeDeltas = diff(timeSeconds);
avgPacketRate = 1 / mean(timeDeltas);
fprintf('Average Packet Rate:         %.2f Hz\n', avgPacketRate);
fprintf('Max Latency Gap Detected:    %.4f seconds\n', max(timeDeltas));
fprintf('----------------------------------------------\n');
fprintf('Signal Strength Metrics (RSSI):\n');
fprintf('  Min: %d dBm | Max: %d dBm | Mean: %.2f dBm\n', min(rssiArray), max(rssiArray), mean(rssiArray));
fprintf('==============================================\n');

%% Step 4: Generate Exploratory Visualizations
figure('Color', [1 1 1], 'Position', [100, 50, 1200, 850], 'Name', 'CSI Exploratory Data Analysis');

% Plot 1: RSSI vs Time
subplot(2, 2, 1);
plot(timeSeconds, rssiArray, 'Color', [0 0.4470 0.7410], 'LineWidth', 1.2);
title('RSSI vs Time (Continuity Check)', 'FontSize', 11);
xlabel('Elapsed Time (Seconds)');
ylabel('RSSI (dBm)');
grid on;

% Plot 2: Histogram of RSSI Distribution
subplot(2, 2, 2);
histogram(rssiArray, 'BinMethod', 'integers', 'FaceColor', [0.3010 0.7450 0.9330], 'EdgeColor', 'w');
title('Distribution of RSSI Values', 'FontSize', 11);
xlabel('RSSI (dBm)');
ylabel('Packet Count');
grid on;

% Plot 3: CSI Amplitude Heatmap
subplot(2, 2, 3);
imagesc(timeSeconds, 1:standardLength, csiMatrix');
colormap('jet');
colorbar_handle = colorbar;
ylabel(colorbar_handle, 'Amplitude');
title('Raw CSI Amplitude Heatmap', 'FontSize', 11);
xlabel('Elapsed Time (Seconds)');
ylabel('Subcarrier Index');
set(gca, 'YDir', 'normal'); 

% Plot 4: Histogram of CSI Amplitudes
subplot(2, 2, 4);
% Strip out the dead pilot/guard subcarriers (0 values) so they don't bias our plot
activeAmplitudes = csiMatrix(csiMatrix ~= 0);
histogram(activeAmplitudes, 40, 'FaceColor', [0.8500 0.3250 0.0980], 'EdgeColor', 'w');
title('Distribution of Active CSI Amplitudes', 'FontSize', 11);
xlabel('Amplitude Value');
ylabel('Frequency');
grid on;