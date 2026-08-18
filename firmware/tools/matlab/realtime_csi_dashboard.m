%% Real-Time CSV-Tailing CSI Dashboard (Anchor A1)
clear; clc; close all;

% --- CONFIGURATION PARAMETERS ---
dataFolder = '../../../data';   
windowSize = 150;       % Number of time-history packets to display
numSubcarriers = 64;    % Standard expected subcarriers from your ESP32
smoothingSpan = 9;      % Moving average span for live noise reduction filter

% --- 1. FIND THE LATEST CSV FILE ---
% Look for all files starting with 'A1_' in the data folder
files = dir(fullfile(dataFolder, 'A1_*.csv'));
if isempty(files)
    error('No A1 CSV files found in the "%s" folder. Run your Python script first!', dataFolder);
end

% Sort by date and pick the newest one
[~, idx] = max([files.datenum]);
latestFile = fullfile(dataFolder, files(idx).name);
fprintf('Tailing Live Data From: %s\n', latestFile);

% --- 2. INITIALIZE ROLLING DATA BUFFERS ---
buffer_A1_raw  = zeros(windowSize, numSubcarriers);
buffer_A1_filt = zeros(windowSize, numSubcarriers);

% --- 3. SETUP LIVE PLOTS ---
fig = figure('Color', [1 1 1], 'Position', [100, 100, 1000, 800], 'Name', 'Live CSI CSV Tailer');

subplot(2,1,1);
hHeat_A1_raw = imagesc(1:windowSize, 1:numSubcarriers, buffer_A1_raw');
colormap(gca, 'jet'); clim([0 60]); title('Anchor A1: RAW CSI Stream (Tailing CSV)');
xlabel('Rolling Packet Window'); ylabel('Subcarrier'); set(gca, 'YDir', 'normal');

subplot(2,1,2);
hHeat_A1_filt = imagesc(1:windowSize, 1:numSubcarriers, buffer_A1_filt');
colormap(gca, 'jet'); clim([0 60]); title('Anchor A1: CLEANED CSI (Dropped Zeros + Smoothed)');
xlabel('Rolling Packet Window'); ylabel('Subcarrier'); set(gca, 'YDir', 'normal');

% --- 4. OPEN FILE FOR CONTINUOUS READING ---
% Using 'r' (read) allows Python to keep writing to it simultaneously
fid = fopen(latestFile, 'r');
if fid == -1
    error('Could not open the CSV file. Ensure it is not locked by Excel.');
end
cleanupObj = onCleanup(@() fclose(fid)); % Ensure file closes if script stops

fprintf('Engine initialized. Waiting for new lines in CSV... Press Ctrl+C to end.\n');

% --- 5. MAIN EXECUTION PIPELINE LOOP ---
newDataAdded = false; % Track if we need to redraw

while ishandle(fig)
    
    % Attempt to read the next line
    lineStr = fgetl(fid);
    
    % If fgetl returns a number (like -1), we hit the current End of File
    if ~ischar(lineStr)
        
        % THE MAGIC TRICK: Clear the MATLAB EOF flag!
        % 'cof' means Current Position. Moving 0 bytes clears the EOF status 
        % so fgetl will actually try reading again on the next loop.
        fseek(fid, 0, 'cof'); 
        
        % If we gathered new data before hitting EOF, update the graph now
        if newDataAdded
            tempFilt = movmean(buffer_A1_filt, smoothingSpan, 1);
            
            set(hHeat_A1_raw, 'CData', buffer_A1_raw');
            set(hHeat_A1_filt, 'CData', tempFilt');
            drawnow limitrate;
            
            newDataAdded = false; % Reset flag until we read more lines
        end
        
        % Pause briefly to let Python write new data and prevent CPU maxing
        pause(0.05); 
        continue; % Skip the parsing below and go back to the top of the loop
    end
    
    % --- If we made it here, we successfully read a new line! ---
    if contains(lineStr, "CSI,A1,")
        lineStr = strrep(lineStr, '"', '');
        parts = split(lineStr, ",");
        
        % Robust Parsing: Grab the absolute last 64 items
        if length(parts) > numSubcarriers
            rawAmplitudes = str2double(parts(end-numSubcarriers+1 : end))';
            
            % Push new data into the raw buffer
            buffer_A1_raw = [buffer_A1_raw(2:end, :); rawAmplitudes];
            
            % Process the filtered buffer
            cleanedAmplitudes = rawAmplitudes;
            nullIdxs = (cleanedAmplitudes == 0);
            if any(nullIdxs)
                cleanedAmplitudes(nullIdxs) = mean(cleanedAmplitudes(~nullIdxs)); 
            end
            
            buffer_A1_filt = [buffer_A1_filt(2:end, :); cleanedAmplitudes];
            newDataAdded = true; % Flag that we have new data to draw
        end
    end
end

