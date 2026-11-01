import React from 'react';
import { Play, Pause, RotateCcw, SkipForward, Clock } from 'lucide-react';

interface PlaybackControlsProps {
  currentStep: number;
  totalSteps: number;
  isPlaying: boolean;
  speed: number;
  simulatedTime: string;
  onPlay: () => void;
  onPause: () => void;
  onReset: () => void;
  onStepForward: () => void;
  onChangeSpeed: (speed: number) => void;
  onSeek: (step: number) => void;
  disabled?: boolean;
}

export const PlaybackControls: React.FC<PlaybackControlsProps> = ({
  currentStep,
  totalSteps,
  isPlaying,
  speed,
  simulatedTime,
  onPlay,
  onPause,
  onReset,
  onStepForward,
  onChangeSpeed,
  onSeek,
  disabled = false,
}) => {
  return (
    <div className="bg-noc-panel border border-noc-border rounded-xl p-4 flex flex-col space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {/* Step Indicator & Clock */}
        <div className="flex items-center space-x-3 text-xs font-mono">
          <div className="flex items-center space-x-2 px-2.5 py-1 rounded bg-noc-subpanel border border-noc-border">
            <span className="text-noc-muted">Step:</span>
            <span className="text-noc-accent font-bold">
              {currentStep} / {totalSteps || 15}
            </span>
          </div>

          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded bg-noc-subpanel border border-noc-border text-noc-muted">
            <Clock className="w-3.5 h-3.5 text-noc-cyan" />
            <span className="text-noc-text">{simulatedTime || '2026-10-31 12:00:00 UTC'}</span>
          </div>
        </div>

        {/* Playback Button Group */}
        <div className="flex items-center space-x-2">
          {isPlaying ? (
            <button
              onClick={onPause}
              disabled={disabled}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium transition-all shadow-md shadow-amber-600/20 disabled:opacity-50"
            >
              <Pause className="w-3.5 h-3.5" />
              <span>Pause Playback</span>
            </button>
          ) : (
            <button
              onClick={onPlay}
              disabled={disabled}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-all shadow-md shadow-indigo-600/20 disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>{currentStep > 0 && currentStep < totalSteps ? 'Resume' : 'Play Simulation'}</span>
            </button>
          )}

          <button
            onClick={onStepForward}
            disabled={disabled || currentStep >= totalSteps}
            title="Step Forward"
            className="p-1.5 rounded-lg bg-noc-subpanel hover:bg-noc-hover text-noc-text border border-noc-border text-xs transition-all disabled:opacity-40"
          >
            <SkipForward className="w-4 h-4" />
          </button>

          <button
            onClick={onReset}
            disabled={disabled}
            title="Reset to Step 0"
            className="p-1.5 rounded-lg bg-noc-subpanel hover:bg-noc-hover text-noc-text border border-noc-border text-xs transition-all disabled:opacity-40"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          {/* Speed Toggle */}
          <div className="flex items-center ml-2 border border-noc-border rounded-lg overflow-hidden bg-noc-subpanel">
            {[1, 2, 5].map(s => (
              <button
                key={s}
                onClick={() => onChangeSpeed(s)}
                className={`px-2.5 py-1 text-[11px] font-mono transition-colors ${
                  speed === s ? 'bg-indigo-600 text-white font-bold' : 'text-noc-muted hover:text-noc-text'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Scrubber Progress Slider */}
      <div className="flex items-center space-x-3">
        <input
          type="range"
          min="0"
          max={totalSteps || 15}
          value={currentStep}
          onChange={e => onSeek(Number(e.target.value))}
          disabled={disabled}
          className="w-full h-1.5 bg-noc-subpanel rounded-lg appearance-none cursor-pointer accent-indigo-500 disabled:opacity-40"
        />
      </div>

      {/* Honest Simulation Behavior Disclaimer */}
      <p className="text-[10px] text-noc-muted font-mono flex items-center justify-between">
        <span>✦ Synthetic Scenario Playback: visual replay of timestamped observations.</span>
        <span className="text-noc-yellow/80">Visual pause does not alter backend diagnosis.</span>
      </p>
    </div>
  );
};
