//
//  QuinnProcess.swift
//  managedsoftwareupdate
//
//  Created by Greg Neagle on 7/26/24.
//

import Foundation

/// Runs the specified tool as a child process, supplying `stdin` and capturing `stdout` and `stderr`.
///
/// - important: Must be run on the main queue.
///
/// - Parameters:
///   - tool: Path to the tool to run.
///   - arguments: The command-line arguments to pass to that tool; defaults to the empty array.
///   - input: Data to pass to the tool’s `stdin`; defaults to empty.
///   - completionHandler: Called on the main queue when the tool has terminated.

func launch(tool: String, arguments: [String] = [], input: Data = Data(), completionHandler: @escaping CompletionHandler) {
    // This precondition is important; read the comment near the `run()` call to
    // understand why.
    dispatchPrecondition(condition: .onQueue(.main))

    let group = DispatchGroup()
    let inputPipe = Pipe()
    let outputPipe = Pipe()
    let errorPipe = Pipe()

    var errorQ: Error?
    var output = Data()
    var errorOut = Data()

    let proc = Process()
    proc.launchPath = tool
    proc.arguments = arguments
    proc.standardInput = inputPipe
    proc.standardOutput = outputPipe
    group.enter()
    proc.terminationHandler = { _ in
        // This bounce to the main queue is important; read the comment near the
        // `run()` call to understand why.
        DispatchQueue.main.async {
            group.leave()
        }
    }

    // This runs the supplied block when all three events have completed (task
    // termination and the end of both I/O channels).
    //
    // - important: If the process was never launched, requesting its
    // termination status raises an Objective-C exception (ouch!).  So, we only
    // read `terminationStatus` if `errorQ` is `nil`.

    group.notify(queue: .main) {
        if let error = errorQ {
            completionHandler(.failure(error), output)
        } else {
            completionHandler(.success(proc.terminationStatus), output)
        }
    }

    do {
        func posixErr(_ error: Int32) -> Error { NSError(domain: NSPOSIXErrorDomain, code: Int(error), userInfo: nil) }

        // If you write to a pipe whose remote end has closed, the OS raises a
        // `SIGPIPE` signal whose default disposition is to terminate your
        // process.  Helpful!  `F_SETNOSIGPIPE` disables that feature, causing
        // the write to fail with `EPIPE` instead.

        let fcntlResult = fcntl(inputPipe.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        guard fcntlResult >= 0 else { throw posixErr(errno) }

        // Actually run the process.

        try proc.run()

        // At this point the termination handler could run and leave the group
        // before we have a chance to enter the group for each of the I/O
        // handlers.  I avoid this problem by having the termination handler
        // dispatch to the main thread.  We are running on the main thread, so
        // the termination handler can’t run until we return, at which point we
        // have already entered the group for each of the I/O handlers.
        //
        // An alternative design would be to enter the group at the top of this
        // block and then leave it in the error hander.  I decided on this
        // design because it has the added benefit of all my code running on the
        // main queue and thus I can access shared mutable state, like `errorQ`,
        // without worrying about thread safety.

        // Enter the group and then set up a Dispatch I/O channel to write our
        // data to the child’s `stdin`.  When that’s done, record any error and
        // leave the group.
        //
        // Note that we ignore the residual value passed to the
        // `write(offset:data:queue:ioHandler:)` completion handler.  Earlier
        // versions of this code passed it along to our completion handler but
        // the reality is that it’s not very useful. The pipe buffer is big
        // enough that it usually soaks up all our data, so the residual is a
        // very poor indication of how much data was actually read by the
        // client.

        group.enter()
        let writeIO = DispatchIO(type: .stream, fileDescriptor: inputPipe.fileHandleForWriting.fileDescriptor, queue: .main) { _ in
            // `FileHandle` will automatically close the underlying file
            // descriptor when you release the last reference to it.  By holidng
            // on to `inputPipe` until here, we ensure that doesn’t happen. And
            // as we have to hold a reference anyway, we might as well close it
            // explicitly.
            //
            // We apply the same logic to `readIO` below.
            try! inputPipe.fileHandleForWriting.close()
        }
        let inputDD = input.withUnsafeBytes { DispatchData(bytes: $0) }
        writeIO.write(offset: 0, data: inputDD, queue: .main) { isDone, _, error in
            if isDone || error != 0 {
                writeIO.close()
                if errorQ == nil, error != 0 { errorQ = posixErr(error) }
                group.leave()
            }
        }

        // Enter the group and then set up a Dispatch I/O channel to read data
        // from the child’s `stdout`.  When that’s done, record any error and
        // leave the group.

        group.enter()
        let readIO = DispatchIO(type: .stream, fileDescriptor: outputPipe.fileHandleForReading.fileDescriptor, queue: .main) { _ in
            try! outputPipe.fileHandleForReading.close()
        }
        readIO.read(offset: 0, length: .max, queue: .main) { isDone, chunkQ, error in
            output.append(contentsOf: chunkQ ?? .empty)
            if isDone || error != 0 {
                readIO.close()
                if errorQ == nil, error != 0 { errorQ = posixErr(error) }
                group.leave()
            }
        }

        // Enter the group and then set up a Dispatch I/O channel to read data
        // from the child’s `stderr`.  When that’s done, record any error and
        // leave the group.

        group.enter()
        let errorIO = DispatchIO(type: .stream, fileDescriptor: errorPipe.fileHandleForReading.fileDescriptor, queue: .main) { _ in
            try! errorPipe.fileHandleForReading.close()
        }
        errorIO.read(offset: 0, length: .max, queue: .main) { isDone, chunkQ, error in
            errorOut.append(contentsOf: chunkQ ?? .empty)
            if isDone || error != 0 {
                errorIO.close()
                if errorQ == nil, error != 0 { errorQ = posixErr(error) }
                group.leave()
            }
        }
    } catch {
        // If either the `fcntl` or the `run()` call threw, we set the error
        // and manually call the termination handler.  Note that we’ve only
        // entered the group once at this point, so the single leave done by the
        // termination handler is enough to run the notify block and call the
        // client’s completion handler.
        errorQ = error
        proc.terminationHandler!(proc)
    }
}

/// Called when the tool has terminated.
///
/// This must be run on the main queue.
///
/// - Parameters:
///   - result: Either the tool’s termination status or, if something went
///   wrong, an error indicating what that was.
///   - output: Data captured from the tool’s `stdout`.

typealias CompletionHandler = (_ result: Result<Int32, Error>, _ output: Data) -> Void
