"""Custom (tintable) weapon cloning for generate.py.

A player custom weapon in CoH is four pieces, all cloned here from a shipped template weapon:
  ent_types/CustomWeapon_<Family>_<Name>.txt                 entity: points at the weapon .geo
  fx/WEAPONS/Custom_<Family>/<Body>_<Family>_<Name>.fx      per body type: spawns the entity on the hand
  tricks/WEAPONS/CustomWeapons.txt   X_CustomWeapon_...     layered texture: base + color mask + bump
  menu/costume/localized/<body>/all/weapons/<menu>.ctm      the option in Power Customization
The geometry itself (player_library/G_WepR_<Family>_<Name>.geo) and its textures come from the
Max 2015 export; this module only wires them up.
"""
import re

import cryptic_text as ct

BODIES = (("male", ("Male",)), ("female", ("Fem", "Female")), ("huge", ("Huge",)))
TRICKS_FILE = "tricks/WEAPONS/CustomWeapons.txt"


def path_pattern(path):
    """Regex for a data path, ignoring case and slash direction."""
    parts = [re.escape(p) for p in re.split(r"[\\/]", path)]
    return re.compile(r"[\\/]".join(parts), re.I)


def replace_path(text, old, new):
    count = 0

    def sub(m):
        nonlocal count
        count += 1
        sep = "\\" if "\\" in m.group(0) else "/"
        return new.replace("/", sep)
    return path_pattern(old).sub(sub, text), count


def find_named_block(text, name):
    """A block named by a Name/FullName field or by its header line (e.g. `Texture X_Foo`)."""
    hit = ct.find_block(text, name, ("Name", "FullName"))
    if hit:
        return hit
    want = name.lower()
    stack = list(ct.parse(text))
    while stack:
        b = stack.pop(0)
        tokens = [t.strip('"').lower() for t in b.header.split()]
        if want in tokens:
            return b
        stack.extend(b.children)
    return None


def block_containing(text, pattern):
    """Innermost block whose text matches pattern."""
    best = None
    stack = list(ct.parse(text))
    while stack:
        b = stack.pop()
        if pattern.search(text[b.start:b.end]):
            best = b if best is None or (b.end - b.start) < (best.end - best.start) else best
            stack.extend(b.children)
    return best


class WeaponNames:
    def __init__(self, family, name):
        self.family, self.name = family, name
        self.short = f"{family}_{name}"
        self.entity = f"CustomWeapon_{family}_{name}"
        self.ent_file = f"ent_types/CustomWeapon_{family}_{name}.txt"
        self.geo = f"G_WepR_{family}_{name}"
        self.geo_file = f"player_library/G_WepR_{family}_{name}.geo"
        self.trick = f"X_CustomWeapon_{family}_{name}"

    def fx_file(self, prefix):
        return f"fx/WEAPONS/Custom_{self.family}/{prefix}_{self.family}_{self.name}.fx"


def gen_custom_weapons(g):
    cw = g.spec.get("custom_weapons")
    if not cw or not cw.get("weapons"):
        return
    tfam, fam = cw["template_family"], cw["family"]
    menu_tpl = cw.get("menu_file", "menu/costume/localized/{body}/all/weapons/inc_weapons_assaultrifles.ctm")
    trick_text = g.read(TRICKS_FILE, required=False)
    trick_added = []
    menu_texts, menu_added, insert_after = {}, {}, {}

    for w in cw["weapons"]:
        old, new = WeaponNames(tfam, w["template"]), WeaponNames(fam, w["name"])
        if w.get("geometry"):
            new.geo = w["geometry"]
            new.geo_file = f"player_library/{w['geometry']}.geo"
        tokens = {old.entity: new.entity, old.geo: new.geo, old.short: new.short, old.trick: new.trick}
        g.weapon_template_ids.update(tokens)
        where = f"Weapon {new.name}"

        # 1. entity type
        src = g.read(old.ent_file)
        if src is not None:
            txt, _ = replace_path(src, old.geo_file, new.geo_file)
            txt, _ = ct.replace_tokens(txt, tokens)
            g.emit(new.ent_file, txt, txt)

        # 2. per-body fx
        fx_paths = {}
        for body, prefixes in BODIES:
            for prefix in prefixes:
                src = g.read(old.fx_file(prefix), required=False)
                if src is None:
                    continue
                new_rel = new.fx_file(prefixes[0])
                txt, _ = ct.replace_tokens(src, tokens)
                g.emit(new_rel, txt, txt)
                fx_paths[body] = (old.fx_file(prefix), new_rel)
                break
            else:
                g.warnings.append(f"{where}: no {body} template fx `{old.fx_file(prefixes[0])}`; {body} option skipped.")

        # 3. layered texture (base + mask + bump)
        tex = w.get("textures") or {}
        if trick_text is not None and any(tex.values()):
            tpl_trick = w.get("trick_template") or old.trick
            b = find_named_block(trick_text, tpl_trick)
            if not b:
                g.errors.append(f"{where}: trick `{tpl_trick}` not found in `{TRICKS_FILE}`; set `trick_template` to one that is.")
            else:
                txt = trick_text[b.start:b.end]
                txt, _ = ct.replace_tokens(txt, {tpl_trick: new.trick})
                for tok in sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", txt)), key=len, reverse=True):
                    role = "mask" if tok.lower().endswith("_mask") else "bump" if tok.lower().endswith("_bump") else None
                    if role is None and re.search(r"(weapon|wep|rifle|gun|sword|katana)", tok, re.I) and tok != new.trick:
                        role = "base"
                    if role and tex.get(role):
                        txt, _ = ct.replace_tokens(txt, {tok: tex[role]})
                    elif role:
                        g.notes.append(f"{where}: layered texture keeps the template {role} `{tok}` (set textures.{role} to replace it).")
                trick_added.append(txt)
        elif any(tex.values()):
            g.warnings.append(f"{where}: `{TRICKS_FILE}` missing; layered texture not generated.")

        # 4. costume menu entry per body
        for body, (old_fx, new_fx) in fx_paths.items():
            rel = menu_tpl.format(body=body)
            if rel not in menu_texts:
                menu_texts[rel] = g.read(rel, required=False)
                menu_added[rel] = []
            text = menu_texts[rel]
            if text is None:
                g.warnings.append(f"{where}: menu `{rel}` missing; add the option by hand.")
                continue
            old_ref = old_fx[len("fx/"):] if old_fx.lower().startswith("fx/") else old_fx
            new_ref = new_fx[len("fx/"):] if new_fx.lower().startswith("fx/") else new_fx
            b = block_containing(text, path_pattern(old_ref))
            if not b:
                g.errors.append(f"{where}: no entry for `{old_ref}` in `{rel}`.")
                continue
            entry, _ = replace_path(text[b.start:b.end], old_ref, new_ref)
            entry, _ = ct.replace_tokens(entry, tokens)
            if w.get("label"):
                entry, had = ct.set_field(entry, g.F["display"], w["label"], quote=True)
                if not had:
                    g.warnings.append(f"{where}: menu entry had no `{g.F['display']}`; added one. Confirm field name.")
            key = w.get("unlock_key")
            if key is not None:
                # Unlock keys look like CustomWeapon_Council_01 (word, then a number); "" means no key.
                tpl_keys = [t for t in set(re.findall(r"CustomWeapon_[A-Za-z]+_\d+", entry)) if t != new.entity]
                for k in tpl_keys:
                    if key:
                        entry, _ = ct.replace_tokens(entry, {k: key})
                    else:
                        lines = entry.split("\n")
                        entry = "\n".join(ln for ln in lines if not ct.find_tokens(ln, [k]))
                        note = f"{where}: dropped template unlock key `{k}` from menu entries."
                        if note not in g.notes:
                            g.notes.append(note)
            # Insert after the template entry (or after earlier clones of it) so options keep spec order.
            insert_at = insert_after.get((rel, old_ref.lower())) or (text.find("\n", b.end - 1) + 1 or len(text))
            text = text[:insert_at] + entry + "\n" + text[insert_at:]
            grown = len(entry) + 1
            for k, pos in insert_after.items():
                if k[0] == rel and pos >= insert_at:
                    insert_after[k] = pos + grown
            insert_after[(rel, old_ref.lower())] = insert_at + grown
            menu_texts[rel] = text
            menu_added[rel].append(entry + "\n")

        g.notes.append(f"{where}: ship `{new.geo_file}` (Max 2015 export)"
                       + (f" and textures {', '.join(v for v in tex.values() if v)}" if any(tex.values()) else "") + ".")

    if trick_added:
        chunk = "\n\n" + "\n\n".join(trick_added) + "\n"
        g.emit(TRICKS_FILE, trick_text.rstrip() + "\n" + chunk, chunk)
    for rel, text in menu_texts.items():
        if text is not None and menu_added[rel]:
            g.emit(rel, text, "".join(menu_added[rel]))
