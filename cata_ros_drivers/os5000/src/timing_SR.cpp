/*------------------------------------------------------------------------------
 *  Title:        timing_SR.cpp
 *  Description:  Functions for timers and checking to see if an amount of
 * 		          time has passed.
 *----------------------------------------------------------------------------*/

/*
 *
 *      Copyright (c) 2010 <iBotics -- www.sdibotics.org>
 *      All rights reserved.
 *
 *      Redistribution and use in source and binary forms, with or without
 *      modification, are permitted provided that the following conditions are
 *      met:
 *
 *      * Redistributions of source code must retain the above copyright
 *        notice, this list of conditions and the following disclaimer.
 *      * Redistributions in binary form must reproduce the above
 *        copyright notice, this list of conditions and the following disclaimer
 *        in the documentation and/or other materials provided with the
 *        distribution.
 *      * Neither the name of the Stingray, iBotics nor the names of its
 *        contributors may be used to endorse or promote products derived from
 *        this software without specific prior written permission.
 *
 *      THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *      "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *      LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 *      A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 *      OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 *      SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 *      LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 *      DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 *      THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 *      (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *      OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */

#include "timing_SR.h"

/*------------------------------------------------------------------------------
 * Timing()
 * Constructor.
 *----------------------------------------------------------------------------*/

Timing::Timing(float _period)
{
    period = _period;
    Setup();
} // end Timing()


/*------------------------------------------------------------------------------
 * ~Timing()
 * Destructor.
 *----------------------------------------------------------------------------*/

Timing::~Timing()
{
} // end ~Timing()


/*------------------------------------------------------------------------------
 * void Setup()
 * Sets up a timer.
 *----------------------------------------------------------------------------*/

void Timing::Setup()
{
    // Set timer to the current system time.
    Set();

    // Initialize variables.
    expired = false;
} // end Setup()


/*------------------------------------------------------------------------------
 * float CheckExpired()
 * Check if a period (in seconds) has elapsed for a timer.
 *----------------------------------------------------------------------------*/

bool Timing::CheckExpired()
{
    // Declare variables.
    struct timeval t = {0, 0};
    int t1 = 0;
    int t2 = 0;

    // Get the current system time.
    gettimeofday(&t, NULL);

    // Convert times to microseconds.
    t1 = (s * 1000000) + us;
    t2 = (t.tv_sec * 1000000) + t.tv_usec;

    // Check to see if period has elapsed.
    if (t2 - t1 > (period * 1000000))
    {
        expired = true;
    }
    else
    {
        expired = false;
    }

    return expired;
} // end CheckExpired()


/*------------------------------------------------------------------------------
 * int Set()
 * Sets a timer to the current system time.
 *----------------------------------------------------------------------------*/

void Timing::Set()
{
    // Declare variables.
    struct timeval t = {0, 0};

    // Get the current system time.
    gettimeofday(&t, NULL);

    // Set timer to the current system time.
    s  = t.tv_sec;
    us = t.tv_usec;
} // end Set()


/*------------------------------------------------------------------------------
 * int GetDt()
 * Get the time elapsed for a given timer. Return the elapsed time in another
 * TIMING element.
 *----------------------------------------------------------------------------*/

int Timing::GetDt()
{
    // Declare variables.
    struct timeval t = {0, 0};
    int elapsedSec = 0;
    int elapsedUsec = 0;

    // Get the current system time.
    gettimeofday(&t, NULL);

    // Check to see which fraction of a second is larger.
    if (t.tv_usec > us)
    {
        elapsedSec = s - t.tv_sec;
        elapsedUsec = 1000000 + us - t.tv_usec;
        // This should never happen. If it does then there is a problem with the system time.
        if (elapsedSec < 0)
            return TIMING_ERROR;
    }
    else
    {
        elapsedSec = s - t.tv_sec;
        elapsedUsec = us - t.tv_usec;
    }

    return elapsedSec * 1000000 + elapsedUsec;
} // end GetDt()


/*------------------------------------------------------------------------------
 * float GetDtS()
 * Get the time elapsed for a given timer in seconds.
 *----------------------------------------------------------------------------*/

float Timing::GetDtS()
{
    // Declare variables.
    struct timeval t = {0, 0};
    int t1 = 0;
    int t2 = 0;

    // Get the current system time.
    gettimeofday(&t, NULL);

    // Convert times to microseconds.
    t1 = s * 1000000 + us;
    t2 = t.tv_sec * 1000000 + t.tv_usec;

    // Return time in seconds.
    return (float)(t2 - t1) / 1000000.;
} // end GetDtS()
