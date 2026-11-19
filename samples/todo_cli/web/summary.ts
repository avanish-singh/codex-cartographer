/**
 * Tiny TypeScript companion — ensures .ts parsing is exercised.
 */

export interface Task {
  id: number;
  title: string;
  done: boolean;
}

export function summarize(tasks: Task[]): string {
  const open = tasks.filter((t) => !t.done).length;
  return `${open} open / ${tasks.length} total`;
}

export function createTask(id: number, title: string): Task {
  return { id, title, done: false };
}
