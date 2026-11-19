/**
 * Companion JS helpers for the sample todo app — gives the cartographer
 * a mixed-language neighborhood to map.
 */

export class TodoView {
  constructor(todos = []) {
    this.todos = todos;
  }

  add(title) {
    const id = this.nextId();
    const item = { id, title, done: false };
    this.todos.push(item);
    return item;
  }

  markDone(id) {
    const item = this.todos.find((t) => t.id === id);
    if (item) {
      item.done = true;
    }
    return item;
  }

  nextId() {
    if (this.todos.length === 0) return 1;
    return Math.max(...this.todos.map((t) => t.id)) + 1;
  }

  render() {
    return this.todos
      .map((t) => `${t.done ? "[x]" : "[ ]"} #${t.id} ${t.title}`)
      .join("\n");
  }
}

export function createView(seed) {
  return new TodoView(seed || []);
}

export function main() {
  const view = createView();
  view.add("Ink the margins");
  view.add("Draw the compass rose");
  console.log(view.render());
}

if (typeof require !== "undefined" && require.main === module) {
  main();
}
