"""Generate a Mastermind power set patch from a spec, using the maintainers' own data tree.

usage:
  python tools/generate.py --data <path to their data root> [--spec spec/spirit_binding.json] [--out out/]
  python tools/generate.py --data <root> --probe      # print template blocks + field names, write nothing

The data root is the folder that contains `defs/` and `Defs/` text sources (the tree the server's
bins are built from). It is only read; everything is written under --out.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
import cryptic_text as ct  # noqa: E402
import weapons  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART_WORDS = re.compile(r"(?i)necromancy|zombie|skelet|(?<![a-z])li(?:t)?ch(?![a-z])|grave_?knight")


class Gen:
    def __init__(self, spec, data_root, catalog=None):
        self.spec = spec
        self.data = data_root
        self.catalog = catalog or {}
        self.F = {"name": "Name", "full_name": "FullName", "display": "DisplayName",
                  "short_help": "DisplayShortHelp", "help": "DisplayHelp", "icon": "IconName",
                  "costume_part": "CostumePart", **spec.get("field_names", {})}
        self.T = spec.get("template", {})
        self.errors, self.warnings, self.notes = [], [], []
        self.outputs = {}          # rel path -> text
        self.new_text = {}         # rel path -> only the content we added (for lint)
        self.token_map = {}
        self.villain_short_map = {}
        self.weapon_template_ids = {}

    # ---------- io ----------
    def path(self, rel):
        p = os.path.join(self.data, *rel.split("/"))
        if os.path.exists(p):
            return p
        # Case-insensitive fallback: the game's own paths mix Defs/ and defs/.
        cur = self.data
        for part in rel.split("/"):
            if not os.path.isdir(cur):
                return None
            match = next((e for e in os.listdir(cur) if e.lower() == part.lower()), None)
            if match is None:
                return None
            cur = os.path.join(cur, match)
        return cur

    def read(self, rel, required=True):
        p = self.path(rel)
        if p is None:
            if required:
                self.errors.append(f"Missing source file `{rel}` under the data root.")
            return None
        with open(p, encoding="latin-1", newline="") as f:
            return f.read()

    def emit(self, rel, text, added):
        self.outputs[rel] = text
        self.new_text[rel] = added

    # ---------- naming ----------
    def tset(self):
        return f'{self.T["category"]}.{self.T["set"]}'

    def nset(self):
        return f'{self.T["category"]}.{self.spec["set"]["name"]}'

    def kit_file(self, kit_set_full):
        cat, s = kit_set_full.split(".", 1)
        return f"defs/powers/{cat}_{s}.powers"

    @staticmethod
    def blocks_named(text, prefix):
        out = []
        for b in ct.parse(text):
            n = ct.block_name(text, b)
            if n and n.startswith(prefix + "."):
                out.append((n, b))
        return out

    # ---------- step 1: build token map ----------
    def build_map(self):
        T, S = self.T, self.spec
        self.token_map[self.tset()] = self.nset()
        set_src = self.read(T["files"]["set_powers"])
        self.set_src = set_src
        if set_src:
            spec_by_tpl = {p["template"]: p for p in S["powers"]}
            seen = set()
            for full, _b in self.blocks_named(set_src, self.tset()):
                short = full.rsplit(".", 1)[1]
                p = spec_by_tpl.get(short)
                new_short = p["name"] if p else short
                if not p:
                    self.warnings.append(f"Template power `{full}` has no entry in spec.powers; cloned as `{new_short}`.")
                self.token_map[full] = f"{self.nset()}.{new_short}"
                seen.add(short)
            for tpl in spec_by_tpl:
                if tpl not in seen:
                    self.errors.append(f"spec.powers references `{tpl}`, which is not in `{T['files']['set_powers']}`.")

        pcat = T["pet_category"]
        self.kit_sources = []   # (template set full, new set full, rel file, text)
        for pet in S["pets"]:
            self.token_map[pet["template_villain"]] = pet["villain"]
            for c in pet["costumes"]:
                if c.get("replaces"):
                    self.token_map[c["replaces"]] = c["name"]
            if not pet.get("template_kit"):
                continue
            overrides = {o["template"]: o for o in pet.get("kit_overrides", [])}
            for suffix in ("", "_2", "_3"):
                tk, nk = pet["template_kit"] + suffix, pet["kit"] + suffix
                tfull, nfull = f"{pcat}.{tk}", f"{pcat}.{nk}"
                rel = self.kit_file(tfull)
                text = self.read(rel, required=(suffix == ""))
                if text is None:
                    if suffix:
                        self.notes.append(f"No `{rel}`; tier `{nk}` skipped.")
                    continue
                self.token_map[tfull] = nfull
                self.villain_short_map[tk] = nk
                for full, _b in self.blocks_named(text, tfull):
                    o = overrides.get(full)
                    new_short = o["name"] if o and o.get("name") else full.rsplit(".", 1)[1]
                    self.token_map[full] = f"{nfull}.{new_short}"
                self.kit_sources.append((tfull, nfull, rel, text, overrides))
        self.token_map.update(S.get("token_map", {}))

    # ---------- helpers ----------
    def apply_fields(self, text, fields, where):
        for k, v in fields.items():
            if v in (None, ""):
                continue
            text, replaced = ct.set_field(text, k, v)
            if not replaced:
                self.warnings.append(f"{where}: field `{k}` was not in the template block, so it was added. Check the field name.")
        return text

    def rename(self, text, full, short):
        text, _ = ct.set_field(text, self.F["full_name"], full, quote=False)
        if ct.field_value(text, ct.parse(text)[0], self.F["name"]) is not None:
            text, _ = ct.set_field(text, self.F["name"], short, quote=False)
        return text

    def set_display(self, text, item, where):
        for key in ("display", "short_help", "help", "icon"):
            if item.get(key):
                text, replaced = ct.set_field(text, self.F[key], item[key], quote=True)
                if not replaced:
                    self.warnings.append(f"{where}: `{self.F[key]}` not found in template; added. Confirm field name.")
        return text

    def set_count(self, text, villain, count, where):
        if count <= 0:
            return text
        kids = [c for c in ct.parse(text)[0].children
                if ct.find_tokens(text[c.start:c.end], [villain])]
        if not kids:
            self.errors.append(f"{where}: no sub-block creates `{villain}`; cannot set count {count}.")
            return text
        have = len(kids)
        if count < have:
            for c in reversed(kids[count:]):
                text = text[:c.start] + text[text.find("\n", c.close) + 1 if "\n" in text[c.close:] else c.end:]
        elif count > have:
            last = kids[-1]
            line_end = text.find("\n", last.close)
            line_end = last.end if line_end < 0 else line_end + 1
            chunk = text[last.start:line_end]
            text = text[:line_end] + chunk * (count - have) + text[line_end:]
        if count != have:
            self.notes.append(f"{where}: pet count {have} -> {count}.")
        return text

    # ---------- step 2: set powers ----------
    def gen_set_powers(self):
        if not self.set_src:
            return
        src = self.set_src
        spec_by_tpl = {p["template"]: p for p in self.spec["powers"]}
        pets_by_power = {p["summon_power"]: p for p in self.spec["pets"] if p.get("summon_power")}
        parts = []
        for full, b in self.blocks_named(src, self.tset()):
            short = full.rsplit(".", 1)[1]
            p = spec_by_tpl.get(short, {"name": short, "fields": {}})
            txt, _ = ct.replace_tokens(src[b.start:b.end], self.token_map)
            txt = self.rename(txt, f"{self.nset()}.{p['name']}", p["name"])
            txt = self.set_display(txt, p, f"Power {p['name']}")
            txt = self.apply_fields(txt, p.get("fields", {}), f"Power {p['name']}")
            pet = pets_by_power.get(p["name"])
            if pet:
                txt = self.set_count(txt, pet["villain"], int(pet.get("count") or 0), f"Power {p['name']}")
            parts.append(txt)
        out = "\n\n".join(parts) + "\n"
        rel = f"defs/powers/{self.T['category']}_{self.spec['set']['name']}.powers"
        self.emit(rel, out, out)

    # ---------- step 3: pet kits ----------
    def gen_kits(self):
        for tfull, nfull, rel, text, overrides in self.kit_sources:
            parts = []
            for full, b in self.blocks_named(text, tfull):
                o = overrides.get(full)
                if o and o.get("from"):
                    src_set = o["from"].rsplit(".", 1)[0]
                    src_text = self.read(self.kit_file(src_set))
                    sb = ct.find_block(src_text, o["from"]) if src_text else None
                    if not sb:
                        self.errors.append(f"Kit override: source power `{o['from']}` not found.")
                        body = text[b.start:b.end]
                    else:
                        body = src_text[sb.start:sb.end]
                else:
                    body = text[b.start:b.end]
                new_full = self.token_map[full]
                txt, _ = ct.replace_tokens(body, self.token_map)
                txt = self.rename(txt, new_full, new_full.rsplit(".", 1)[1])
                if o:
                    txt = self.apply_fields(txt, o.get("fields", {}), f"Kit power {new_full}")
                parts.append(txt)
            out = "\n\n".join(parts) + "\n"
            self.emit(self.kit_file(nfull), out, out)

    # ---------- step 4: powersets + categories ----------
    def clone_into(self, rel, names, finish):
        text = self.read(rel)
        if text is None:
            return
        added = []
        for tname, nname in names:
            b = ct.find_block(text, tname)
            if not b:
                self.errors.append(f"`{tname}` not found in `{rel}`.")
                continue
            txt, _ = ct.replace_tokens(text[b.start:b.end], self.token_map)
            txt = finish(txt, tname, nname)
            added.append(txt)
        if added:
            chunk = "\n\n" + "\n\n".join(added) + "\n"
            self.emit(rel, text.rstrip() + "\n" + chunk, chunk)

    def gen_powersets(self):
        S = self.spec

        def finish_set(txt, _t, nname):
            txt = self.rename(txt, nname, S["set"]["name"])
            return self.set_display(txt, S["set"], f"Powerset {nname}")

        self.clone_into(self.T["files"]["set_powersets"], [(self.tset(), self.nset())], finish_set)
        kit_names = [(t, n) for t, n, *_ in self.kit_sources]
        self.clone_into(self.T["files"]["pet_powersets"], kit_names,
                        lambda txt, _t, n: self.rename(txt, n, n.split(".", 1)[1]))

    def patch_category(self, rel, category, pairs):
        text = self.read(rel)
        if text is None:
            return
        b = ct.find_block(text, category)
        if not b:
            self.errors.append(f"Category `{category}` not found in `{rel}`.")
            return
        added = []
        for tname, nname in pairs:
            seg = text[b.start:b.end]
            hit = ct.find_tokens(seg, [tname])
            if not hit:
                self.errors.append(f"`{tname}` not listed in category `{category}` ({rel}).")
                continue
            line_no = hit[0][1]
            lines = seg.split("\n")
            new_line = ct.replace_tokens(lines[line_no - 1], {tname: nname})[0]
            lines.insert(line_no, new_line)
            seg = "\n".join(lines)
            text = text[:b.start] + seg + text[b.end:]
            b = ct.find_block(text, category)
            added.append(new_line + "\n")
        self.emit(rel, text, "".join(added))

    def gen_categories(self):
        self.patch_category(self.T["files"]["set_categories"], self.T["category"], [(self.tset(), self.nset())])
        self.patch_category(self.T["files"]["pet_categories"], self.T["pet_category"],
                            [(t, n) for t, n, *_ in self.kit_sources])

    # ---------- step 5: villains ----------
    def gen_villains(self):
        pets = self.spec["pets"]

        def finish(txt, tname, nname):
            pet = next(p for p in pets if p["villain"] == nname)
            txt, _ = ct.replace_tokens(txt, self.villain_short_map)
            txt, _ = ct.set_field(txt, self.F["name"], nname, quote=False)
            return self.apply_fields(txt, pet.get("villain_fields", {}), f"Villain {nname}")

        self.clone_into(self.T["files"]["villains"], [(p["template_villain"], p["villain"]) for p in pets], finish)

    # ---------- step 6: costumes ----------
    @staticmethod
    def hex_rgb(h):
        h = h.lstrip("#")
        return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"

    def descendants(self, text, keyword):
        found = []

        def walk(bs):
            for b in bs:
                if b.keyword == keyword:
                    found.append(b)
                walk(b.children)
        walk(ct.parse(text)[0].children)
        return found

    def edit_parts(self, txt, selector, fields):
        part_kw = self.F["costume_part"]
        parts = self.descendants(txt, part_kw)
        if selector == "*":
            chosen = parts
        elif selector.startswith("#"):
            i = int(selector[1:])
            chosen = parts[i:i + 1]
        else:
            k, _, v = selector.partition("=")
            chosen = [p for p in parts if ct.field_value(txt, p, k.strip()) == v.strip()]
        if not chosen:
            self.warnings.append(f"Costume part selector `{selector}` matched nothing.")
        for p in sorted(chosen, key=lambda b: b.start, reverse=True):
            seg = txt[p.start:p.end]
            for k, v in fields.items():
                if v not in (None, ""):
                    seg, _ = ct.set_field(seg, k, v)
            txt = txt[:p.start] + seg + txt[p.end:]
        return txt

    def apply_costume_fields(self, txt, fields, where):
        """Edit a field where it already lives (NPC block or its nested Costume block); add it to the
        innermost non-part block otherwise."""
        part_kw = self.F["costume_part"]
        for k, v in fields.items():
            if v in (None, ""):
                continue
            root = ct.parse(txt)[0]
            candidates, stack = [], [root]
            while stack:
                b = stack.pop(0)
                if b.keyword != part_kw:
                    candidates.append(b)
                    stack.extend(b.children)
            target = next((b for b in candidates if k in ct.own_field_names(txt, b)), None)
            if target is None:
                target = candidates[-1]
                self.warnings.append(f"{where}: field `{k}` not in source costume; added to `{target.keyword}` block. Check the field name.")
            seg, _ = ct.set_field(txt[target.start:target.end], k, v)
            txt = txt[:target.start] + seg + txt[target.end:]
        return txt

    def gen_costumes(self):
        sources = [(rel, self.read(rel, required=False)) for rel in self.T["files"]["costume_sources"]]
        sources = [(r, t) for r, t in sources if t]
        added = []
        for pet in self.spec["pets"]:
            for c in pet["costumes"]:
                src = next(((r, t, b) for r, t in sources for b in [ct.find_block(t, c["from"], ("Name",))] if b), None)
                if not src:
                    self.errors.append(f"Costume source `{c['from']}` not found in {[r for r, _ in sources]}.")
                    continue
                _r, t, b = src
                txt = t[b.start:b.end]
                txt, _ = ct.set_field(txt, self.F["name"], c["name"], quote=False)
                txt = self.apply_costume_fields(txt, c.get("fields", {}), f"Costume {c['name']}")
                tint = c.get("tint") or {}
                tint_fields = {}
                if tint.get("primary"):
                    tint_fields["Color1"] = self.hex_rgb(tint["primary"])
                if tint.get("secondary"):
                    tint_fields["Color2"] = self.hex_rgb(tint["secondary"])
                if tint_fields:
                    txt = self.edit_parts(txt, "*", tint_fields)
                for part in c.get("parts", []):
                    txt = self.edit_parts(txt, part.get("select", "*"), part.get("fields", {}))
                added.append(txt)
        if added:
            out = "\n\n".join(added) + "\n"
            self.emit(self.T["files"]["costume_output"], out, out)

    # ---------- step 7: lint ----------
    def lint(self):
        template_ids = set(self.token_map) | set(self.villain_short_map)
        template_ids.discard("")
        # Power category/set names also show up in the costume catalog; they are not costumes.
        set_parts = {seg for s in self.catalog.get("powersets", []) for seg in s.split(".")}
        costumes = set(self.catalog.get("costumes", [])) - set_parts
        new_costumes = {c["name"] for p in self.spec.get("pets", []) for c in p["costumes"]}
        for rel, added in self.new_text.items():
            for tok, line in ct.find_tokens(added, list(self.token_map)):
                self.errors.append(f"`{rel}` (added text, line {line}): still references template `{tok}`.")
            if costumes and rel.endswith(".villain"):
                for w in set(re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", added)):
                    if w in costumes and w not in new_costumes and w not in template_ids:
                        self.errors.append(f"`{rel}`: cloned villain still uses template costume `{w}`. Add it to a costume's `replaces`.")
            for tok, line in ct.find_tokens(added, list(self.weapon_template_ids)):
                self.errors.append(f"`{rel}` (added text, line {line}): still references template weapon `{tok}`.")
            art = [(i, s.strip()) for i, s in enumerate(added.split("\n"), 1) if ART_WORDS.search(s)]
            if art:
                shown = "; ".join(f"L{i} `{s[:80]}`" for i, s in art[:4])
                more = f" (+{len(art) - 4} more)" if len(art) > 4 else ""
                self.warnings.append(f"Art pass, `{rel}`: {len(art)} lines still name the template art/powers: {shown}{more}")

    # ---------- run ----------
    def run(self):
        has_set = bool(self.spec.get("powers"))
        if has_set:
            self.build_map()
        if not self.errors:
            if has_set:
                self.gen_set_powers()
                self.gen_kits()
                self.gen_powersets()
                self.gen_categories()
                self.gen_villains()
                self.gen_costumes()
            weapons.gen_custom_weapons(self)
            self.lint()
        return self

    def report(self):
        title = (self.spec.get("set") or {}).get("display") or self.spec.get("meta", {}).get("title", "patch")
        L = [f"# Patch report: {title}", ""]
        L.append(f"**{len(self.errors)} errors, {len(self.warnings)} warnings.** "
                 "Errors must be fixed before handing this to the maintainers.")
        L += ["", "## Files", ""]
        for rel in sorted(self.outputs):
            kind = "new" if self.outputs[rel] == self.new_text[rel] else "patched copy"
            L.append(f"- `{rel}` ({kind})")
        for title, items in (("Errors", self.errors), ("Notes", self.notes), ("Warnings", self.warnings)):
            L += ["", f"## {title}", ""] + ([f"- {x}" for x in items] or ["- none"])
        L += ["", "## Identifier map", "", "| template | new |", "|---|---|"]
        L += [f"| `{k}` | `{v}` |" for k, v in sorted(self.token_map.items())]
        L += [f"| `{k}` (villain power list) | `{v}` |" for k, v in sorted(self.villain_short_map.items())]
        return "\n".join(L) + "\n"

    def write(self, out_dir):
        for rel, text in self.outputs.items():
            p = os.path.join(out_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="latin-1", newline="") as f:
                f.write(text)
        with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8") as f:
            f.write(self.report())


def probe(spec, data_root):
    g = Gen(spec, data_root)
    files = dict(g.T["files"])
    files.pop("costume_output", None)
    for key, rels in files.items():
        for rel in (rels if isinstance(rels, list) else [rels]):
            text = g.read(rel, required=False)
            print(f"\n=== {key}: {rel} {'(missing)' if text is None else ''}")
            if not text:
                continue
            for b in ct.parse(text)[:3]:
                print(f"  {b.keyword} `{ct.block_name(text, b)}` fields: {', '.join(ct.own_field_names(text, b))}")
                for c in b.children[:4]:
                    print(f"    {c.keyword} fields: {', '.join(ct.own_field_names(text, c))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="maintainers' data root (contains defs/)")
    ap.add_argument("--spec", default=os.path.join(ROOT, "spec", "spirit_binding.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    if a.probe:
        probe(spec, a.data)
        return 0
    cat_path = os.path.join(ROOT, "editor", "catalog.json")
    catalog = json.load(open(cat_path, encoding="utf-8")) if os.path.exists(cat_path) else {}
    g = Gen(spec, a.data, catalog).run()
    g.write(a.out)
    print(g.report().split("\n## Identifier map")[0])
    return 1 if g.errors else 0


if __name__ == "__main__":
    sys.exit(main())
