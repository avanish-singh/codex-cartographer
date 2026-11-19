package demo;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/** Orchestrates loading, cleaning and summarizing a text dataset. */
public class Pipeline {

    private final Path source;

    public Pipeline(Path source) {
        this.source = source;
    }

    public List<String> load() throws IOException {
        return Files.readAllLines(source);
    }

    public List<String> clean(List<String> lines) {
        return lines.stream().map(String::trim).filter(s -> !s.isEmpty()).toList();
    }

    public Summary summarize(List<String> lines) {
        int words = 0;
        for (String line : lines) {
            words += line.split("\\s+").length;
        }
        return new Summary(lines.size(), words);
    }

    public static void main(String[] args) throws IOException {
        Pipeline pipeline = new Pipeline(Path.of(args[0]));
        List<String> lines = pipeline.clean(pipeline.load());
        Summary summary = pipeline.summarize(lines);
        System.out.println(summary);
    }
}

record Summary(int lines, int words) {}
