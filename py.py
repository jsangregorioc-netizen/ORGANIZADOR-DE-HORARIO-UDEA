
# app.py
# Ejecuta: pip install streamlit pandas
# Luego:   streamlit run app.py

import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

import pandas as pd
import streamlit as st

# -----------------------------
# Modelo y parser
# -----------------------------

# Incluye D (domingo) porque aparece en tus datos
DAY_ORDER = ["L", "M", "W", "J", "V", "S", "D"]
DAY_LABELS = {"L": "Lun", "M": "Mar", "W": "Mié", "J": "Jue", "V": "Vie", "S": "Sáb", "D": "Dom"}
DAY_SET = set(DAY_ORDER)

@dataclass(frozen=True)
class Session:
    day: str
    start: int  # hora inicio (entero)
    end: int    # hora fin (entero), no incluida
    room: Optional[str]  # "09318", "VIRTUAL", "UDE@", None

@dataclass
class Group:
    number: int
    sessions: List[Session]
    cupo_max: Optional[int] = None
    cupo_disp: Optional[int] = None
    professors: Optional[str] = None

@dataclass
class Course:
    code: Optional[str]
    name: str
    groups: List[Group]

# Horarios tipo "LMWJ6-8", "WV12-14", "LWJV18-20"
SLOT_RE = re.compile(r"^([LMWJVSD]+)(\d{1,2})-(\d{1,2})$")

def parse_schedule_line(value: str) -> List[Session]:
    """
    Parsea:
      - "03101 LW10-12"
      - "VIRTUAL D8-12"
      - "UDE@ MJ6-8"
      - "WV12-14" (sin aula)
    """
    tokens = value.strip().split()
    if not tokens:
        return []

    # Si el primer token ya es un slot (p.ej. WV12-14), entonces no hay aula
    m0 = SLOT_RE.match(tokens[0])
    if m0:
        room = None
        slot_tokens = tokens[:]
    else:
        room = tokens[0]
        slot_tokens = tokens[1:]

    sessions: List[Session] = []
    for tok in slot_tokens:
        m = SLOT_RE.match(tok)
        if not m:
            # Token no reconocido (robustez): ignorar
            continue

        days_str, start_s, end_s = m.group(1), m.group(2), m.group(3)
        start, end = int(start_s), int(end_s)

        # Validación simple (horas enteras)
        if start < 0 or start > 23 or end < 1 or end > 24 or end <= start:
            continue

        for d in days_str:
            if d in DAY_SET:
                sessions.append(Session(day=d, start=start, end=end, room=room))
    return sessions

def parse_courses(text: str) -> List[Course]:
    # Conservamos orden pero removemos líneas vacías
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() != ""]
    courses: List[Course] = []

    # Materia: [9013104] ENGLISH 4   (case-insensitive)
    MAT_RE  = re.compile(r"^materia:\s*(\[(?P<code>[^\]]+)\])?\s*(?P<name>.+)$", re.IGNORECASE)
    GRP_RE  = re.compile(r"^grupo:\s*(\d+)\s*$", re.IGNORECASE)
    AYH_RE  = re.compile(r"^aula\s+y\s+horario:\s*(.+)$", re.IGNORECASE)
    CUP_RE  = re.compile(r"^cupo\s+m[aá]ximo:\s*(\d+)\.\s*cupo\s+disponible:\s*(\d+)\s*$", re.IGNORECASE)
    PROF_RE = re.compile(r"^profesor\(es\):\s*(.+)$", re.IGNORECASE)

    current_course: Optional[Course] = None
    current_group: Optional[Group] = None

    def flush_group():
        nonlocal current_group, current_course
        if current_course and current_group:
            current_course.groups.append(current_group)
        current_group = None

    def flush_course():
        nonlocal current_course
        if current_course:
            flush_group()
            courses.append(current_course)
        current_course = None

    i = 0
    while i < len(lines):
        ln = lines[i].strip()

        m_mat = MAT_RE.match(ln)
        if m_mat:
            flush_course()
            code = m_mat.group("code")
            name = m_mat.group("name").strip()
            current_course = Course(code=code, name=name, groups=[])
            i += 1
            continue

        m_grp = GRP_RE.match(ln)
        if m_grp:
            flush_group()
            gnum = int(m_grp.group(1))
            current_group = Group(number=gnum, sessions=[])
            i += 1
            continue

        if current_group:
            m_ayh = AYH_RE.match(ln)
            if m_ayh:
                current_group.sessions.extend(parse_schedule_line(m_ayh.group(1)))
                i += 1
                continue

            m_cup = CUP_RE.match(ln)
            if m_cup:
                current_group.cupo_max = int(m_cup.group(1))
                current_group.cupo_disp = int(m_cup.group(2))
                i += 1
                continue

            m_prof = PROF_RE.match(ln)
            if m_prof:
                current_group.professors = m_prof.group(1).strip()
                i += 1
                continue

        i += 1

    flush_course()
    return courses

# -----------------------------
# Conflictos (rango [start, end))
# -----------------------------

def overlaps(a: Session, b: Session) -> bool:
    if a.day != b.day:
        return False
    return not (a.end <= b.start or b.end <= a.start)

def group_conflicts(g1: Group, g2: Group) -> bool:
    for s1 in g1.sessions:
        for s2 in g2.sessions:
            if overlaps(s1, s2):
                return True
    return False

# -----------------------------
# Helpers de UI
# -----------------------------

def course_key(c: Course) -> str:
    # clave estable para session_state
    return (c.code or c.name).strip()

def group_label(g: Group) -> str:
    disp = g.cupo_disp if g.cupo_disp is not None else "?"
    mx = g.cupo_max if g.cupo_max is not None else "?"
    # Resumen de sesiones
    sess = []
    for s in sorted(g.sessions, key=lambda x: (DAY_ORDER.index(x.day), x.start, x.end)):
        room = s.room if s.room else "-"
        sess.append(f"{s.day}{s.start}-{s.end} ({room})")
    sess_txt = ", ".join(sess) if sess else "Sin horario"
    return f"Grupo {g.number} | Cupo {disp}/{mx} | {sess_txt}"

def build_selected_sessions(courses: List[Course], selected_groups: Dict[str, Optional[int]]) -> List[Tuple[str, int, Session]]:
    """
    Retorna lista de (curso_key, grupo_numero, session)
    """
    out = []
    course_by_key = {course_key(c): c for c in courses}
    for ck, gnum in selected_groups.items():
        if gnum is None:
            continue
        c = course_by_key.get(ck)
        if not c:
            continue
        g = next((gr for gr in c.groups if gr.number == gnum), None)
        if not g:
            continue
        for s in g.sessions:
            out.append((ck, gnum, s))
    return out

def make_schedule_table(courses: List[Course], selected_groups: Dict[str, Optional[int]]) -> pd.DataFrame:
    """
    Tabla: filas por hora, columnas por día (L..D).
    Cada celda contiene textos (pueden apilarse).
    """
    sel = build_selected_sessions(courses, selected_groups)
    if not sel:
        # Tabla vacía estándar 6-20
        hours = list(range(6, 21))
        df = pd.DataFrame({DAY_LABELS[d]: [""] * len(hours) for d in DAY_ORDER}, index=hours)
        df.index.name = "Hora"
        return df

    min_h = min(s.start for _, _, s in sel)
    max_h = max(s.end for _, _, s in sel)
    min_h = max(0, min_h)
    max_h = min(24, max_h)
    if max_h <= min_h:
        min_h, max_h = 6, 21

    hours = list(range(min_h, max_h))
    df = pd.DataFrame({DAY_LABELS[d]: [""] * len(hours) for d in DAY_ORDER}, index=hours)
    df.index.name = "Hora"

    # Para mapear key -> nombre corto
    course_by_key = {course_key(c): c for c in courses}

    for ck, gnum, s in sel:
        cname = course_by_key[ck].name
        room = s.room if s.room else "-"
        block = f"{cname}\nG{gnum}\n{room}"
        col = DAY_LABELS[s.day]
        for h in range(s.start, s.end):
            if h in df.index:
                df.at[h, col] = (df.at[h, col] + ("\n---\n" if df.at[h, col] else "") + block)

    return df

def make_day_list(courses: List[Course], selected_groups: Dict[str, Optional[int]]) -> Dict[str, List[str]]:
    sel = build_selected_sessions(courses, selected_groups)
    if not sel:
        return {DAY_LABELS[d]: [] for d in DAY_ORDER}

    course_by_key = {course_key(c): c for c in courses}
    per_day: Dict[str, List[Tuple[int, int, str]]] = {d: [] for d in DAY_ORDER}

    for ck, gnum, s in sel:
        cname = course_by_key[ck].name
        room = s.room if s.room else "-"
        per_day[s.day].append((s.start, s.end, f"{s.start}-{s.end} | {cname} | G{gnum} | {room}"))

    out: Dict[str, List[str]] = {}
    for d in DAY_ORDER:
        items = sorted(per_day[d], key=lambda x: (x[0], x[1], x[2]))
        out[DAY_LABELS[d]] = [t[2] for t in items]
    return out

def compute_group_status(
    course: Course,
    courses: List[Course],
    selected_groups: Dict[str, Optional[int]],
) -> List[Dict]:
    """
    Para cada grupo del curso, devuelve estado:
      - cupo_ok
      - conflict (con selecciones actuales de otras materias)
      - selectable
      - reason
    """
    ck = course_key(course)

    # grupos seleccionados de otras materias
    other_selected: List[Group] = []
    course_by_key = {course_key(c): c for c in courses}
    for other_ck, gnum in selected_groups.items():
        if other_ck == ck or gnum is None:
            continue
        oc = course_by_key.get(other_ck)
        if not oc:
            continue
        og = next((gr for gr in oc.groups if gr.number == gnum), None)
        if og:
            other_selected.append(og)

    rows = []
    for g in course.groups:
        cupo_ok = (g.cupo_disp is None) or (g.cupo_disp > 0)
        conflict = any(group_conflicts(g, og) for og in other_selected)
        selectable = cupo_ok and (not conflict)

        reason = []
        if not cupo_ok:
            reason.append("SIN CUPO")
        if conflict:
            reason.append("CHOQUE")
        if not reason:
            reason_txt = "OK"
        else:
            reason_txt = " + ".join(reason)

        rows.append({
            "Grupo": g.number,
            "Cupo disponible": g.cupo_disp,
            "Cupo máximo": g.cupo_max,
            "Profesor(es)": g.professors,
            "Horario": ", ".join(
                f"{s.day}{s.start}-{s.end}({s.room if s.room else '-'})"
                for s in sorted(g.sessions, key=lambda x: (DAY_ORDER.index(x.day), x.start))
            ) or "Sin horario",
            "Estado": reason_txt,
            "_selectable": selectable,
        })
    return rows

# -----------------------------
# Streamlit App
# -----------------------------

st.set_page_config(page_title="Organizador de Horario", layout="wide")

st.title("Organizador de horario universitario (MVP)")
st.caption("Pega el texto, procesa, selecciona materias y grupos. El horario se actualiza en vivo. "
           "Rangos [inicio, fin): L10-12 ocupa 10-11 y a las 12 ya queda libre.")

default_text = ""
if "raw_text" not in st.session_state:
    st.session_state.raw_text = default_text
if "courses" not in st.session_state:
    st.session_state.courses = []
if "included" not in st.session_state:
    st.session_state.included = {}  # ck -> bool
if "selected_groups" not in st.session_state:
    st.session_state.selected_groups = {}  # ck -> Optional[int]

with st.expander("Entrada de datos", expanded=True):
    st.session_state.raw_text = st.text_area(
        "Pega aquí tus materias/grupos:",
        value=st.session_state.raw_text,
        height=260,
        placeholder="Materia: [2018040] ...",
    )
    colA, colB = st.columns([1, 3])
    with colA:
        if st.button("Procesar", type="primary"):
            courses = parse_courses(st.session_state.raw_text)
            st.session_state.courses = courses

            # inicializar estados
            included = {}
            selected = {}
            for c in courses:
                ck = course_key(c)
                included[ck] = True  # por defecto incluidas (puedes cambiarlo)
                selected[ck] = None
            st.session_state.included = included
            st.session_state.selected_groups = selected

    with colB:
        st.write(f"Materias detectadas: **{len(st.session_state.courses)}**")

courses: List[Course] = st.session_state.courses

if not courses:
    st.info("Pega tus datos y presiona **Procesar**.")
    st.stop()

left, right = st.columns([1.15, 1.85], gap="large")

with left:
    st.subheader("Selección")
    st.write("Marca materias e indica un grupo por materia. Los grupos sin cupo o con choque no se podrán elegir.")

    # Por cada materia: incluir + selector de grupo (solo opciones seleccionables)
    for c in courses:
        ck = course_key(c)
        header = f"{c.name}" + (f" [{c.code}]" if c.code else "")
        with st.container(border=True):
            inc = st.checkbox(header, value=st.session_state.included.get(ck, True), key=f"inc_{ck}")
            st.session_state.included[ck] = inc

            if not inc:
                st.session_state.selected_groups[ck] = None
                st.caption("Materia excluida.")
                continue

            # Tabla de estado de grupos (siempre mostrar todos)
            status_rows = compute_group_status(c, courses, st.session_state.selected_groups)
            status_df = pd.DataFrame([{
                "Grupo": r["Grupo"],
                "Cupo": f'{r["Cupo disponible"]}/{r["Cupo máximo"]}',
                "Horario": r["Horario"],
                "Estado": r["Estado"],
                "Profesor(es)": r["Profesor(es)"] or ""
            } for r in status_rows])
            st.dataframe(status_df, use_container_width=True, hide_index=True)

            # Opciones seleccionables
            selectable = [r for r in status_rows if r["_selectable"]]
            selectable_numbers = [r["Grupo"] for r in selectable]

            current = st.session_state.selected_groups.get(ck, None)
            # Si el actual ya no es seleccionable (por un cambio en otra materia), lo limpiamos
            if current is not None and current not in selectable_numbers:
                st.session_state.selected_groups[ck] = None
                current = None

            # Selector solo con grupos seleccionables, pero la tabla arriba muestra TODOS
            options = ["— Sin seleccionar —"] + [str(n) for n in selectable_numbers]
            default_index = 0 if current is None else (options.index(str(current)) if str(current) in options else 0)

            chosen = st.selectbox(
                "Elegir grupo (solo disponibles y sin choque):",
                options=options,
                index=default_index,
                key=f"sel_{ck}",
            )
            if chosen == "— Sin seleccionar —":
                st.session_state.selected_groups[ck] = None
            else:
                st.session_state.selected_groups[ck] = int(chosen)

with right:
    st.subheader("Horario en vivo")

    # Construimos vistas solo con materias incluidas
    included_courses = [c for c in courses if st.session_state.included.get(course_key(c), True)]
    included_selected = {
        course_key(c): st.session_state.selected_groups.get(course_key(c), None)
        for c in included_courses
    }

    # Tabla semanal
    df = make_schedule_table(included_courses, included_selected)
    st.write("**Tabla semanal (hora vs día)**")
    st.dataframe(df, use_container_width=True)

    # Lista por día
    st.write("**Lista por día**")
    day_list = make_day_list(included_courses, included_selected)
    cols = st.columns(len(DAY_ORDER))
    for col, d in zip(cols, DAY_ORDER):
        with col:
            st.markdown(f"**{DAY_LABELS[d]}**")
            items = day_list[DAY_LABELS[d]]
            if not items:
                st.caption("—")
            else:
                for it in items:
                    st.write(it)

    # Resumen de selecciones
    st.divider()
    st.write("**Selección actual**")
    summary = []
    course_by_key = {course_key(c): c for c in included_courses}
    for ck, gnum in included_selected.items():
        if gnum is None:
            continue
        cname = course_by_key[ck].name
        summary.append(f"- {cname}: Grupo {gnum}")
    st.markdown("\n".join(summary) if summary else "— Sin grupos seleccionados —")

