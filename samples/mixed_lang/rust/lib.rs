use std::collections::HashMap;

/// A tiny bag-of-words counter used by the demo.
pub struct Vocabulary {
    counts: HashMap<String, usize>,
}

impl Vocabulary {
    pub fn new() -> Self {
        Vocabulary { counts: HashMap::new() }
    }

    pub fn add_text(&mut self, text: &str) {
        for token in tokenize(text) {
            *self.counts.entry(token).or_insert(0) += 1;
        }
    }

    pub fn most_common(&self, k: usize) -> Vec<(&String, &usize)> {
        let mut items: Vec<_> = self.counts.iter().collect();
        items.sort_by(|a, b| b.1.cmp(a.1));
        items.into_iter().take(k).collect()
    }
}

pub fn tokenize(text: &str) -> Vec<String> {
    text.split_whitespace()
        .map(|t| t.to_lowercase())
        .collect()
}

fn main() {
    let mut vocab = Vocabulary::new();
    vocab.add_text("the quick brown fox jumps over the lazy dog");
    println!("{:?}", vocab.most_common(3));
}
