%% Step 1: Select Both CSV Files
% Enable MultiSelect to grab both A1 and A2 logs at the same time
[files, path] = uigetfile('*.csv', 'Select exactly TWO Gateway Logger CSV Files', 'MultiSelect', 'on');

if ~iscell(files) || length(files) ~= 2
    error('Please hold CTRL (or CMD) and click exactly TWO CSV files to compare.');
end

%% Step 2: Parse Both Files
anchorData = struct(); % Data structure to hold both anchors independently

for k = 1:2
    filePath = fullfile(path, files{k});
    opts = detectImportOptions(filePath);
    opts.VariableNamingRule = 'preserve';
    data = readtable(filePath, opts);
    
    % Filter valid CSI lines
    data.line = string(data.line);
    csiRows = data(startsWith(data.line, "CSI,"), :);
    numRaw = height(csiRows);
    
    % Preallocate
    parsedRSSI = zeros(numRaw, 1);
    parsedTimestamps = csiRows.host_ns;
    rawCSIList = cell(numRaw, 1);
    
    for i = 1:numRaw
        lineStr = strrep(csiRows.line(i), '"', '');
        parts = split(lineStr, ",");
        
        parsedRSSI(i) = str2double(parts(5));
        % Subcarriers start at index 11
        rawCSIList{i} = str2double(parts(11:end))'; 
    end
    
    % Dynamic length filtering to drop the corrupted first line
    lengths = cellfun(@length, rawCSIList);
    stdLen = mode(lengths);
    validIdx = (lengths == stdLen);
    
    % Extract Anchor ID dynamically from the first valid line
    firstValidStr = strrep(csiRows.line(find(validIdx, 1, 'first')), '"', '');
    idParts = split(firstValidStr, ",");
    
    % Store cleaned data into our structure
    anchorData(k).filename = files{k};
    anchorData(k).anchorID = string(idParts(2)); 
    anchorData(k).rssi = parsedRSSI(validIdx);
    anchorData(k).timeNs = parsedTimestamps(validIdx);
    anchorData(k).csiMatrix = cat(1, rawCSIList{validIdx});
    anchorData(k).stdLen = stdLen;
    anchorData(k).activeAmps = anchorData(k).csiMatrix(anchorData(k).csiMatrix ~= 0);
end

%% Step 3: Global Time Synchronization
% Find the absolute earliest timestamp across both anchors
globalStartNs = min(anchorData(1).timeNs(1), anchorData(2).timeNs(1));

% Convert to elapsed seconds using the shared global start time
anchorData(1).timeSec = double(anchorData(1).timeNs - globalStartNs) / 1e9;
anchorData(2).timeSec = double(anchorData(2).timeNs - globalStartNs) / 1e9;

%% Step 4: Generate Side-by-Side Exploratory Visualizations
figure('Color', [1 1 1], 'Position', [50, 50, 1600, 950], 'Name', 'Dual-Anchor CSI EDA Dashboard');

% Title mapping for the columns
for k = 1:2
    anchorTitle = sprintf('Anchor %s', anchorData(k).anchorID);
    
    % --- Row 1: RSSI vs Time ---
    subplot(4, 2, k);
    plot(anchorData(k).timeSec, anchorData(k).rssi, 'Color', [0 0.4470 0.7410], 'LineWidth', 1.2);
    title([anchorTitle ' - RSSI vs Time'], 'FontSize', 11, 'FontWeight', 'bold');
    xlabel('Elapsed Time (Seconds)');
    ylabel('RSSI (dBm)');
    grid on;
    % Lock the X-axis limit so both charts span the exact same timeframe
    xlim([0 max(anchorData(1).timeSec(end), anchorData(2).timeSec(end))]);
    
    % --- Row 2: RSSI Histogram ---
    subplot(4, 2, k + 2);
    histogram(anchorData(k).rssi, 'BinMethod', 'integers', 'FaceColor', [0.3010 0.7450 0.9330], 'EdgeColor', 'w');
    title([anchorTitle ' - RSSI Distribution'], 'FontSize', 11);
    xlabel('RSSI (dBm)');
    ylabel('Packet Count');
    grid on;
    
    % --- Row 3: CSI Amplitude Heatmap ---
    subplot(4, 2, k + 4);
    imagesc(anchorData(k).timeSec, 1:anchorData(k).stdLen, anchorData(k).csiMatrix');
    colormap(gca, 'jet');
    colorbar_handle = colorbar;
    ylabel(colorbar_handle, 'Amplitude');
    title([anchorTitle ' - Raw CSI Heatmap'], 'FontSize', 11);
    xlabel('Elapsed Time (Seconds)');
    ylabel('Subcarrier Index');
    set(gca, 'YDir', 'normal'); 
    xlim([0 max(anchorData(1).timeSec(end), anchorData(2).timeSec(end))]); % Sync X-axis
    
    % --- Row 4: CSI Amplitude Histogram ---
    subplot(4, 2, k + 6);
    histogram(anchorData(k).activeAmps, 40, 'FaceColor', [0.8500 0.3250 0.0980], 'EdgeColor', 'w');
    title([anchorTitle ' - Active CSI Amplitudes'], 'FontSize', 11);
    xlabel('Amplitude Value');
    ylabel('Frequency');
    grid on;
end