import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const directory = path.dirname(fileURLToPath(import.meta.url));

export function combineConverterSources(coreSource, wrapperSource) {
    const wrapperLines = wrapperSource.split('\n');
    const imports = wrapperLines.filter((line) =>
        line.startsWith('import ') && !line.includes("'./vimar_30805_core.js'"));
    const wrapperBody = wrapperLines.filter((line) => !line.startsWith('import '))
        .join('\n').replace(/^\n+/, '');
    let coreEnd = coreSource.length;
    while (coreEnd > 0 && coreSource[coreEnd - 1] === '\n') coreEnd--;
    const coreBody = coreSource.slice(0, coreEnd)
        .replace(/^export const /gm, 'const ')
        .replace(/^export function /gm, 'function ');
    return `${imports.join('\n')}\n\n${coreBody}\n\n${wrapperBody}`;
}

export async function buildExternalConverter() {
    const [core, wrapper] = await Promise.all([
        readFile(path.join(directory, 'vimar_30805_core.js'), 'utf8'),
        readFile(path.join(directory, 'vimar_30805.js'), 'utf8'),
    ]);
    const outputDirectory = path.join(directory, 'dist');
    const output = path.join(outputDirectory, 'vimar_30805.js');
    await mkdir(outputDirectory, {recursive: true});
    await writeFile(output, combineConverterSources(core, wrapper), 'utf8');
    return output;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    console.log(await buildExternalConverter());
}
