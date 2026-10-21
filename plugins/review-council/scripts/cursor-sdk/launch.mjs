import {pathToFileURL} from 'node:url';

let classify;
try {
  const [driver,...arguments_] = process.argv.slice(2);
  const {runDriver,driverFailure} = await import(pathToFileURL(driver));
  classify = driverFailure;
  const code = await runDriver(arguments_);
  if (Number.isInteger(code) && code >= 0 && code <= 255) process.exitCode = code;
} catch (error) {
  const failure = typeof classify === 'function' ? classify(error)
    : {reason:'sdk_initialization_failed',exitCode:1};
  process.stderr.write(failure.reason + '\n');
  process.exitCode = failure.exitCode;
}
