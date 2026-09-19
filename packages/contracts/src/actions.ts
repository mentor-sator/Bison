import { z } from "zod";
import type { DownstreamService } from "./execution.js";
import { NonEmptyStringSchema } from "./primitives.js";

export const ActionTypeSchema = z.enum([
  "write_file",
  "run_python_script",
  "run_python_module",
  "install_python_packages",
  "open_in_editor",
]);

export const TaskRunnerActionSpecSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("write_file"),
    path: NonEmptyStringSchema,
    content: z.string(),
  }),
  z.object({
    type: z.literal("run_python_script"),
    script_path: NonEmptyStringSchema,
    arguments: z.array(z.string()),
  }),
  z.object({
    type: z.literal("run_python_module"),
    module: NonEmptyStringSchema,
    arguments: z.array(z.string()),
  }),
  z.object({
    type: z.literal("install_python_packages"),
    packages: z.array(NonEmptyStringSchema).min(1),
  }),
]);

export const DevEnvActionSpecSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("open_in_editor"),
    path: NonEmptyStringSchema,
    line: z.number().int().positive().nullable(),
  }),
]);

export const ActionSpecSchema = z.discriminatedUnion("type", [
  ...TaskRunnerActionSpecSchema.options,
  ...DevEnvActionSpecSchema.options,
]);

export type ActionType = z.infer<typeof ActionTypeSchema>;
export type ActionSpec = z.infer<typeof ActionSpecSchema>;
export type TaskRunnerActionSpec = z.infer<typeof TaskRunnerActionSpecSchema>;
export type DevEnvActionSpec = z.infer<typeof DevEnvActionSpecSchema>;

export const ACTION_MENUS = {
  "task-runner": TaskRunnerActionSpecSchema.options.map((option) => option.shape.type.value),
  "dev-env": DevEnvActionSpecSchema.options.map((option) => option.shape.type.value),
} as const satisfies Partial<Record<DownstreamService, readonly ActionType[]>>;

const _actionTypeCoverage: Record<ActionType, true> = ActionSpecSchema.options.reduce(
  (acc, option) => ({ ...acc, [option.shape.type.value]: true }),
  {} as Record<ActionType, true>,
);

void _actionTypeCoverage;
