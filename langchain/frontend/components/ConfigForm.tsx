"use client";

import { useState, type FormEvent } from "react";

export interface ConfigFormValues {
  openaiApiKey: string;
  model: string;
  operatorGoals: string;
  targetMode: "files" | "github";
  files: File[];
  githubUrl: string;
  galileoApiKey: string;
  galileoProject: string;
  maxDirectedWorkers: number;
  maxConcurrent: number;
  maxCycles: number;
}

const MODEL_OPTIONS = ["gpt-5.6-luna", "gpt-5.6-mini", "gpt-5.6"];

const initialValues: ConfigFormValues = {
  openaiApiKey: "",
  model: MODEL_OPTIONS[0],
  operatorGoals: "sql-injection, path-traversal, auth-bypass",
  targetMode: "files",
  files: [],
  githubUrl: "",
  galileoApiKey: "",
  galileoProject: "foundry-harness",
  maxDirectedWorkers: 4,
  maxConcurrent: 4,
  maxCycles: 5,
};

export default function ConfigForm({
  onSubmit,
  submitting,
  submitError,
}: {
  onSubmit: (values: ConfigFormValues) => void;
  submitting: boolean;
  submitError: string | null;
}) {
  const [values, setValues] = useState<ConfigFormValues>(initialValues);
  const [showAdvanced, setShowAdvanced] = useState(false);

  function update<K extends keyof ConfigFormValues>(key: K, value: ConfigFormValues[K]) {
    setValues((prev) => ({ ...prev, [key]: value }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit(values);
  }

  const canSubmit =
    values.openaiApiKey.trim().length > 0 &&
    values.operatorGoals.trim().length > 0 &&
    (values.targetMode === "files" ? values.files.length > 0 : values.githubUrl.trim().length > 0);

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6 max-w-xl w-full">
      <div className="flex flex-col gap-1">
        <label htmlFor="openaiApiKey" className="text-sm font-medium">
          OpenAI API key
        </label>
        <input
          id="openaiApiKey"
          type="password"
          autoComplete="off"
          required
          value={values.openaiApiKey}
          onChange={(e) => update("openaiApiKey", e.target.value)}
          placeholder="sk-..."
          className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
        />
        <p className="text-xs text-black/50 dark:text-white/50">
          Held in memory for this session only. Never logged, never stored.
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="model" className="text-sm font-medium">
          Model
        </label>
        <select
          id="model"
          value={values.model}
          onChange={(e) => update("model", e.target.value)}
          className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
        >
          {MODEL_OPTIONS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="operatorGoals" className="text-sm font-medium">
          Operator goals
        </label>
        <input
          id="operatorGoals"
          type="text"
          required
          value={values.operatorGoals}
          onChange={(e) => update("operatorGoals", e.target.value)}
          placeholder="sql-injection, path-traversal"
          className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
        />
        <p className="text-xs text-black/50 dark:text-white/50">Comma-separated vulnerability classes to prioritize.</p>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="text-sm font-medium mb-1">Target</legend>
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-1.5">
            <input
              type="radio"
              name="targetMode"
              checked={values.targetMode === "files"}
              onChange={() => update("targetMode", "files")}
            />
            Upload files
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="radio"
              name="targetMode"
              checked={values.targetMode === "github"}
              onChange={() => update("targetMode", "github")}
            />
            GitHub URL
          </label>
        </div>

        {values.targetMode === "files" ? (
          <input
            type="file"
            multiple
            onChange={(e) => update("files", Array.from(e.target.files ?? []))}
            className="text-sm"
          />
        ) : (
          <input
            type="url"
            value={values.githubUrl}
            onChange={(e) => update("githubUrl", e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
          />
        )}
      </fieldset>

      <button
        type="button"
        onClick={() => setShowAdvanced((v) => !v)}
        className="text-sm text-left text-black/60 dark:text-white/60 underline underline-offset-2 w-fit"
      >
        {showAdvanced ? "Hide" : "Show"} advanced options
      </button>

      {showAdvanced && (
        <div className="flex flex-col gap-4 rounded-md border border-black/10 dark:border-white/15 p-4">
          <div className="flex flex-col gap-1">
            <label htmlFor="galileoApiKey" className="text-sm font-medium">
              Galileo API key (optional)
            </label>
            <input
              id="galileoApiKey"
              type="password"
              autoComplete="off"
              value={values.galileoApiKey}
              onChange={(e) => update("galileoApiKey", e.target.value)}
              className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="galileoProject" className="text-sm font-medium">
              Galileo project
            </label>
            <input
              id="galileoProject"
              type="text"
              value={values.galileoProject}
              onChange={(e) => update("galileoProject", e.target.value)}
              className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor="maxDirectedWorkers" className="text-xs font-medium">
                Max directed workers
              </label>
              <input
                id="maxDirectedWorkers"
                type="number"
                min={1}
                value={values.maxDirectedWorkers}
                onChange={(e) => update("maxDirectedWorkers", Number(e.target.value))}
                className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="maxConcurrent" className="text-xs font-medium">
                Max concurrent
              </label>
              <input
                id="maxConcurrent"
                type="number"
                min={1}
                value={values.maxConcurrent}
                onChange={(e) => update("maxConcurrent", Number(e.target.value))}
                className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="maxCycles" className="text-xs font-medium">
                Max cycles
              </label>
              <input
                id="maxCycles"
                type="number"
                min={1}
                value={values.maxCycles}
                onChange={(e) => update("maxCycles", Number(e.target.value))}
                className="rounded-md border border-black/15 dark:border-white/20 bg-transparent px-3 py-2 text-sm"
              />
            </div>
          </div>
        </div>
      )}

      {submitError && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {submitError}
        </p>
      )}

      <button
        type="submit"
        disabled={!canSubmit || submitting}
        className="rounded-md bg-foreground text-background px-4 py-2 text-sm font-medium disabled:opacity-40 w-fit"
      >
        {submitting ? "Starting..." : "Start assessment"}
      </button>
    </form>
  );
}
