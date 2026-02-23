# SUTRA – Medidas relacionadas a temas (Educación, San Juan, Trabajadores, Salarios)

Este repositorio extrae medidas/proyectos de ley desde:
https://sutra.oslpr.org/medidas

y filtra solo aquellas que mencionan explícitamente al menos uno de estos temas:
- Departamento de Educación
- Municipio de San Juan
- Trabajadores
- Salarios

## Salida
Genera: `data/medidas_filtradas.json` con los campos:
1) numero_o_nombre
2) titulo_completo
3) fecha_radicacion (ISO)
4) resumen_breve (heurístico basado en el título)
5) palabras_clave (temas detectados)

## Uso local
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/sutra_scraper.py --max-pages 200 --delay 0.25
