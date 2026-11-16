// Applies the website's migrations (001-005) then db/migrations on an embedded PostgreSQL (PGlite) and
// checks the rules the model promises.   node db/check_schema.mjs <dir with the website's migrations>
// Needs:  npm install @electric-sql/pglite   (run it from a folder that has it in node_modules)
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';

const here = dirname(fileURLToPath(import.meta.url));
const webMigrations = resolve(process.argv[2] ?? '');
const db = new PGlite();
const apply = async (dir) => {
  for (const f of readdirSync(dir).filter((n) => n.endsWith('.sql')).sort()) {
    await db.exec(readFileSync(join(dir, f), 'utf8'));
    console.log('applied', f);
  }
};
await apply(webMigrations);
await apply(join(here, 'migrations'));
await apply(join(here, 'migrations'));            // idempotent: a second run changes nothing and does not fail

let failed = 0;
const sha = (c) => c.repeat(64);
const ok = async (name, sql, params = []) => {
  try { await db.query(sql, params); console.log('  ok      ', name); }
  catch (e) { failed++; console.log('  FAILED  ', name, '->', e.message); }
};
const refused = async (name, sql, params = []) => {
  try { await db.query(sql, params); failed++; console.log('  FAILED  ', name, '-> accepted, should be refused'); }
  catch (e) { console.log('  refused ', name, `(${e.message.slice(0, 70)})`); }
};

await ok('two restaurants', `INSERT INTO restaurants(id,name,slug) VALUES ('ra','Chez A','chez-a'),('rb','Chez B','chez-b')`);
await ok('a dish in each', `INSERT INTO dishes(id,restaurant_id,name,price_cents) VALUES ('da','ra','Tajine',1800),('db','rb','Pizza',1200)`);
await ok('file of A under its prefix',
  `INSERT INTO storage_objects(id,restaurant_id,bucket,object_key,kind,mime_type,byte_size,sha256,state)
   VALUES ('oa','ra','media','r/ra/dishes/da/models/m1/model.glb','model_glb','model/gltf-binary',1000,$1,'ready')`, [sha('a')]);
await ok('file of B under its prefix',
  `INSERT INTO storage_objects(id,restaurant_id,bucket,object_key,kind,mime_type,byte_size,sha256,state)
   VALUES ('ob','rb','media','r/rb/dishes/db/models/m1/model.glb','model_glb','model/gltf-binary',1000,$1,'ready')`, [sha('b')]);
await refused('file of A stored under the prefix of B',
  `INSERT INTO storage_objects(id,restaurant_id,bucket,object_key,kind,mime_type,byte_size,sha256)
   VALUES ('ox','ra','media','r/rb/stolen.glb','model_glb','model/gltf-binary',1,$1)`, [sha('c')]);
await refused('same storage key twice',
  `INSERT INTO storage_objects(id,restaurant_id,bucket,object_key,kind,mime_type,byte_size,sha256)
   VALUES ('oy','ra','media','r/ra/dishes/da/models/m1/model.glb','model_glb','model/gltf-binary',1,$1)`, [sha('d')]);
await ok('model of A with its own file',
  `INSERT INTO dish_models(id,restaurant_id,dish_id,revision,method,engine,state,glb_object_id)
   VALUES ('ma1','ra','da',1,'gaussian_splat','gsplat-1.5.3','published','oa')`);
await refused('model of A pointing at a file of B',
  `INSERT INTO dish_models(id,restaurant_id,dish_id,revision,method,engine,glb_object_id)
   VALUES ('ma2','ra','da',2,'stereo_mesh','p1-0.2.0','ob')`);
await refused('model of A attached to a dish of B',
  `INSERT INTO dish_models(id,restaurant_id,dish_id,revision,method,engine) VALUES ('ma3','ra','db',1,'stereo_mesh','p1-0.2.0')`);
await refused('second published model for the same dish',
  `INSERT INTO dish_models(id,restaurant_id,dish_id,revision,method,engine,state,glb_object_id)
   VALUES ('ma4','ra','da',3,'stereo_mesh','p1-0.2.0','published','oa')`);
await refused('published model without any file',
  `INSERT INTO dish_models(id,restaurant_id,dish_id,revision,method,engine,state) VALUES ('mb1','rb','db',1,'stereo_mesh','p1-0.2.0','published')`);
await ok('two QR codes for A (menu, and a table pointing at a dish)',
  `INSERT INTO qr_codes(id,restaurant_id,code,label,target,dish_id) VALUES ('q1','ra','chez-a-menu','Menu','menu',NULL),('q2','ra','chez-a-t12','Table 12','dish','da')`);
await refused('QR code of A pointing at a dish of B',
  `INSERT INTO qr_codes(id,restaurant_id,code,target,dish_id) VALUES ('q3','ra','chez-a-x','dish','db')`);
await refused('same QR code text for two restaurants',
  `INSERT INTO qr_codes(id,restaurant_id,code) VALUES ('q4','rb','chez-a-menu')`);
await refused('photo with neither bytes nor a stored file',
  `INSERT INTO media_assets(id,restaurant_id,mime_type,byte_size,sha256) VALUES ('p1','ra','image/jpeg',10,$1)`, [sha('e')]);
await ok('its own look for A', `INSERT INTO restaurant_themes(restaurant_id,accent_color) VALUES ('ra','#C0392B')`);
await refused('a colour that is not a colour', `INSERT INTO restaurant_themes(restaurant_id,accent_color) VALUES ('rb','rouge')`);
await ok('custom domain for A', `INSERT INTO restaurant_domains(hostname,restaurant_id) VALUES ('menu.chez-a.example','ra')`);
await refused('same domain for B', `INSERT INTO restaurant_domains(hostname,restaurant_id) VALUES ('menu.chez-a.example','rb')`);
await ok('a diner opens a dish from the table QR', `INSERT INTO menu_events(restaurant_id,qr_code_id,dish_id,event) VALUES ('ra','q2','da','model_open')`);
await ok('deleting restaurant A removes everything it owns', `DELETE FROM restaurants WHERE id='ra'`);
const left = await db.query(`SELECT (SELECT count(*) FROM storage_objects WHERE restaurant_id='ra')::int AS files,
  (SELECT count(*) FROM dish_models WHERE restaurant_id='ra')::int AS models, (SELECT count(*) FROM qr_codes WHERE restaurant_id='ra')::int AS qr,
  (SELECT count(*) FROM storage_objects WHERE restaurant_id='rb')::int AS files_b`);
const r = left.rows[0];
if (r.files || r.models || r.qr || r.files_b !== 1) { failed++; console.log('  FAILED   leftovers', r); } else console.log('  ok       nothing of A left, B untouched', r);
console.log(failed ? `${failed} check(s) FAILED` : 'all checks passed');
process.exit(failed ? 1 : 0);
